"""
change_detection.py
===================

Incremental-crawl support: lets a re-crawl UPDATE only the URLs whose content
actually changed, instead of re-parsing/re-writing all 140k+ rows every run.

Mechanism (layered gates, cheapest first)
-----------------------------------------
Per URL, on a re-visit:

  1. HTTP conditional request -- send `If-None-Match` / `If-Modified-Since`
     using the stored ETag / Last-Modified. A `304 Not Modified` means the
     server itself says the page is unchanged -> skip everything.
     (Only used for pages previously classified STATIC; JS-heavy pages are
     always re-fetched with a body so they can be re-rendered -- see below.)

  2. Raw-HTML hash -- SHA-256 of the fetched HTML. If it matches the stored
     `source_hash`, the page is byte-identical -> skip the (expensive) parse
     and the DB write. Used for STATIC pages.

  3. Markdown hash -- SHA-256 of the final rendered markdown. If it matches the
     stored `content_hash`, the *content* is unchanged even if the HTML wrapper
     differed (rotating tokens, ad slots) -> skip the DB write. This is the gate
     for JS-heavy pages, which must be rendered to be compared.

Only when a gate is NOT satisfied does the row get re-written.

Correctness bias
----------------
The design never produces a false "unchanged" for a real content change on the
gated paths: JS-heavy pages are always rendered and compared on their markdown,
and the 304 / raw-HTML fast paths are only trusted for pages known to be static.
The worst case is a false "changed" (an unnecessary re-write) -- harmless.

All heavy dependencies (network, browser) live in the caller (spider.py). This
module is pure hashing + SQL, so it is unit-tested without a crawl.
"""

import hashlib

try:
    from db_setup import DB_CONFIG  # noqa: F401  (re-exported for callers)
except Exception:  # pragma: no cover - allows importing in isolation for tests
    DB_CONFIG = None

CRAWLED_TABLE = "crawled_data"

# Columns this module manages on top of the base (url, raw_markdown, snippet, keywords).
HASH_COLUMNS = {
    "content_hash": "TEXT",          # sha256 of raw_markdown (the stored content)
    "source_hash": "TEXT",           # sha256 of the fetched raw HTML
    "http_etag": "TEXT",             # last seen ETag response header
    "http_last_modified": "TEXT",    # last seen Last-Modified response header
    "is_js_heavy": "BOOLEAN",        # last classification (routes the fast path)
    "last_checked": "TIMESTAMPTZ",   # when we last visited (changed or not)
    "content_updated_at": "TIMESTAMPTZ",  # when raw_markdown last actually changed
}


# ==========================================
# PURE HELPERS  (unit-tested, no side effects)
# ==========================================
def sha256_text(text) -> str:
    """Stable SHA-256 hex of a string (utf-8). Empty/None -> hash of ''."""
    if text is None:
        text = ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def hashes_match(new_hash, stored_hash) -> bool:
    """True only if both are present and equal. A missing stored hash (first
    sighting) is never a match, so new rows always get written."""
    return bool(new_hash) and bool(stored_hash) and new_hash == stored_hash


def conditional_headers(stored) -> dict:
    """Build If-None-Match / If-Modified-Since headers for a re-fetch.

    Returns headers ONLY for a page we previously classified STATIC
    (`is_js_heavy is False`) and for which we hold a validator. For unknown or
    JS-heavy pages we return {} so the caller does a full GET (needs the body to
    classify / render), avoiding a 304 that would wrongly skip a JS page.
    """
    if not stored:
        return {}
    if stored.get("is_js_heavy") is not False:
        return {}
    headers = {}
    if stored.get("http_etag"):
        headers["If-None-Match"] = stored["http_etag"]
    if stored.get("http_last_modified"):
        headers["If-Modified-Since"] = stored["http_last_modified"]
    return headers


def classify_decision(is_js_heavy, source_hash, stored):
    """After a 200 fetch, decide whether the raw-HTML fast path can skip parsing.

    Returns "skip_unchanged" if a STATIC page's raw HTML is byte-identical to
    last time (no need to parse or write); otherwise "parse" (caller must render
    / markdownify and then apply the markdown-hash write gate).
    """
    if not is_js_heavy and stored and hashes_match(source_hash, stored.get("source_hash")):
        return "skip_unchanged"
    return "parse"


def write_decision(markdown_hash, stored):
    """After parsing/rendering, decide whether to write. "skip_unchanged" when
    the markdown hash matches the stored content; else "update"."""
    if stored and hashes_match(markdown_hash, stored.get("content_hash")):
        return "skip_unchanged"
    return "update"


# ==========================================
# DATABASE LAYER
# ==========================================
def ensure_hash_columns(conn, table: str = None):
    """Idempotently add the change-detection columns to the crawl table."""
    table = table or CRAWLED_TABLE
    with conn.cursor() as cur:
        for col, coltype in HASH_COLUMNS.items():
            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {coltype};"
            )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_last_checked "
            f"ON {table} (last_checked);"
        )
    conn.commit()


def get_row_state(conn, url: str, table: str = None):
    """Return the stored change-detection state for a URL, or None if the row
    doesn't exist yet."""
    table = table or CRAWLED_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT content_hash, source_hash, http_etag, http_last_modified,
                       is_js_heavy
                FROM {table} WHERE url = %s;""",
            (url,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "content_hash": row[0],
        "source_hash": row[1],
        "http_etag": row[2],
        "http_last_modified": row[3],
        "is_js_heavy": row[4],
    }


def record_unchanged(conn, url, source_hash, etag, last_modified, is_js_heavy,
                     table: str = None):
    """Page visited but content unchanged: refresh validators + last_checked,
    leave raw_markdown / content_hash / content_updated_at untouched."""
    table = table or CRAWLED_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""UPDATE {table}
                SET source_hash = COALESCE(%s, source_hash),
                    http_etag = %s,
                    http_last_modified = %s,
                    is_js_heavy = %s,
                    last_checked = NOW()
                WHERE url = %s;""",
            (source_hash, etag, last_modified, is_js_heavy, url),
        )
    conn.commit()


def touch_last_checked(conn, url, table: str = None):
    """304 path: nothing changed, just record that we looked."""
    table = table or CRAWLED_TABLE
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {table} SET last_checked = NOW() WHERE url = %s;", (url,))
    conn.commit()


def upsert_content(conn, url, markdown, snippet, keywords, source_hash,
                   etag, last_modified, is_js_heavy, table: str = None):
    """Insert or update a row whose content actually changed (or is new).
    Recomputes content_hash from the markdown and stamps content_updated_at."""
    table = table or CRAWLED_TABLE
    content_hash = sha256_text(markdown)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {table} (url, raw_markdown, snippet, keywords,
                                 content_hash, source_hash, http_etag,
                                 http_last_modified, is_js_heavy,
                                 last_checked, content_updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (url) DO UPDATE SET
                raw_markdown       = EXCLUDED.raw_markdown,
                snippet            = EXCLUDED.snippet,
                keywords           = EXCLUDED.keywords,
                content_hash       = EXCLUDED.content_hash,
                source_hash        = EXCLUDED.source_hash,
                http_etag          = EXCLUDED.http_etag,
                http_last_modified = EXCLUDED.http_last_modified,
                is_js_heavy        = EXCLUDED.is_js_heavy,
                last_checked       = NOW(),
                content_updated_at = NOW();
            """,
            (url, markdown, snippet, keywords, content_hash, source_hash,
             etag, last_modified, is_js_heavy),
        )
    conn.commit()
    return content_hash
