"""
hash_aware_ocr_fleet.py
=======================

PDF OCR fleet. TWO modes:

  * TARGETED (default, current strategy) -- OCR exactly the PDFs listed in
    `pdf_ocr_targets` (seeded by `seed_citizen_charter_targets.py`). No page
    scanning: the PDF URLs are known up front. Each PDF's text is written to
    `crawled_data_ocr`, keyed by its page URL. Run: `python hash_aware_ocr_fleet.py`.

  * SCAN (legacy, `--scan`) -- discover PDFs by crawling topic-keyword pages,
    with the restart-safe content-hash / URL-skip change detection below.

Restart-safe PDF OCR fleet with content-hash change detection.

Problem this solves
-------------------
`vision_ocr_fleet.py` / `sweep_stragglers_fleet.py` track progress with a
URL-based checkpoint file only. On restart they either re-OCR a URL's PDFs
from scratch or skip the whole URL. There is no notion of *whether the PDF
itself changed*. Re-OCRing an unchanged 30-page Bengali PDF wastes GPU time
and, because the old scripts blindly append, duplicates text into
`crawled_data.raw_markdown`.

This script keeps a per-PDF content hash in `pdf_ocr_cache`. On every run it
downloads each PDF, computes its SHA-256, and:

  * hash unchanged  -> SKIP OCR. If the cached OCR block is somehow missing
                       from `crawled_data_ocr` (row was reset), it is
                       re-inserted from the cache -- still no OCR.
  * hash changed    -> RE-OCR, replace that PDF's block in `crawled_data_ocr`,
                       update the cache.
  * new PDF         -> OCR, insert cache, append the block.

OCR text lives in its own table, `crawled_data_ocr(url, ocr_markdown,
updated_at)`, keyed by the page URL -- NOT appended into
`crawled_data.raw_markdown`. `raw_markdown` stays pure HTML-derived content;
`crawled_data_ocr.ocr_markdown` holds everything OCR'd from that page's PDFs.
Pre-existing rows where legacy fleets already appended OCR text into
`raw_markdown` are handled by the one-time `migrate_split_ocr_table.py`
migration, which lives alongside this script and reuses its
`split_markdown_ocr` helper.

Within `ocr_markdown`, each PDF's OCR text is still wrapped in unique
START/END markers keyed by the PDF URL, so a re-run replaces that PDF's block
in place instead of appending a duplicate.

Design for testability
-----------------------
The heavy dependencies (vLLM OCR, pdf2image, network) are injected. The pure
decision/formatting helpers (`compute_pdf_hash`, `decide_action`,
`build_ocr_block`, `replace_ocr_block`) have no side effects and are covered by
`test_hash_aware_ocr.py`, which also exercises the DB layer against throwaway
tables so production data is never touched.
"""

import asyncio
import base64
import gc
import hashlib
import io
import os
import re

import httpx
import psycopg2
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from pdf2image import convert_from_bytes
from tqdm import tqdm
from urllib.parse import urljoin

# ==========================================
# 1. CONFIGURATION
# ==========================================
VLLM_API_BASE = "http://localhost:5000/v1"
VLLM_API_KEY = "no-key"
MODEL_NAME = "qwen36"

DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432",
}

CACHE_TABLE = "pdf_ocr_cache"
CRAWLED_TABLE = "crawled_data"
OCR_TABLE = "crawled_data_ocr"
# Fixed work-list of PDF URLs to OCR (current strategy: OCR only these, not a
# topic-keyword page scan). Seeded by seed_citizen_charter_targets.py.
TARGETS_TABLE = "pdf_ocr_targets"
# When True, the targeted fleet re-scans crawled_data for citizen-charter PDFs
# and appends any new ones to the targets table BEFORE OCRing -- so a fresh
# re-crawl's new charters get picked up automatically (no separate seed step).
AUTO_SEED = True

# Transient errors (download failure, vLLM blip, empty OCR) requeue a target as
# 'pending' up to this many attempts before it is marked terminally 'failed'.
# This stops a one-off outage (e.g. power cut before vLLM is back) from burning
# the whole work-list to 'failed'.
MAX_OCR_ATTEMPTS = 3

CHECKPOINT_FILE = "data/hash_ocr_checkpoint.txt"
# No per-PDF page cap: OCR every page of the document. (A 50MB byte-size shield,
# MAX_PDF_BYTES, still guards against pathologically large files.)
NUM_NETWORK_WORKERS = 50
NUM_GPU_WORKERS = 3
MAX_PDF_BYTES = 250_000_000
MAX_HTML_BYTES = 2_000_000

# Incremental skip strategy:
#   URL_SKIP_MODE = True  -> a PDF URL already present in pdf_ocr_cache is skipped
#     BEFORE download (no fetch, no OCR). Correct for content-addressed / immutable
#     PDF URLs (this corpus): a changed document appears at a new URL. This is the
#     default for routine incremental runs. Seed the cache first with
#     `seed_pdf_cache_from_existing.py` so already-OCR'd PDFs are skipped.
#   URL_SKIP_MODE = False -> full content-hash verification: every PDF is
#     downloaded and SHA-256'd, re-OCR'd only if the bytes changed (`--deep`).
URL_SKIP_MODE = True

# Kept identical to vision_ocr_fleet so the sweep's NOT LIKE filter still works.
OCR_HUMAN_TAG = "### [OCR EXTRACTED FROM ATTACHED PDF] ###"

client = AsyncOpenAI(api_key=VLLM_API_KEY, base_url=VLLM_API_BASE)
pbar = None

TOPIC_KEYWORDS = {
    "জাতীয় পরিচয়পত্র (NID)": ["জাতীয় পরিচয়পত্র", "এনআইডি", "NID", "পরিচয়পত্র"],
    "জন্ম ও মৃত্যু নিবন্ধন (Birth/Death)": ["জন্ম নিবন্ধন", "মৃত্যু নিবন্ধন", "জন্ম সনদ", "মৃত্যু সনদ"],
    "ট্রেড লাইসেন্স (Trade License)": ["ট্রেড লাইসেন্স", "Trade License"],
    "ভূমি সেবা (Land Services)": ["ভূমি সেবা", "খতিয়ান", "পর্চা", "নামজারি", "ভূমি কর", "ই-নামজারি"],
    "পাসপোর্ট (Passport)": ["পাসপোর্ট", "Passport", "ই-পাসপোর্ট", "e-passport"],
    "যানবাহন ও লাইসেন্স (Vehicle/License)": ["ড্রাইভিং লাইসেন্স", "যানবাহন নিবন্ধন", "বিআরটিএ", "BRTA", "রুট পারমিট"],
    "ইউটিলিটি বিল (Utility Bills)": ["বিদ্যুৎ বিল", "গ্যাস বিল", "পানি বিল", "ডেসকো", "ডিপিডিসি", "ওয়াসা", "তিতাস"],
    "স্বাস্থ্য সেবা (Health Services)": ["স্বাস্থ্য সেবা", "হাসপাতাল", "চিকিৎসা", "স্বাস্থ্য অধিদপ্তর", "DGHS", "DGDA"],
}

# ==========================================
# 2. PURE HELPERS  (no side effects -> unit tested)
# ==========================================
def compute_pdf_hash(pdf_bytes: bytes) -> str:
    """SHA-256 hex digest of the raw PDF bytes. Deterministic; the whole change
    detection rests on this being stable for identical content."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def is_valid_pdf(pdf_bytes: bytes) -> bool:
    """Magic-byte + size shield. Mirrors the guard in the legacy fleets."""
    if not pdf_bytes:
        return False
    if len(pdf_bytes) > MAX_PDF_BYTES:
        return False
    return pdf_bytes.lstrip()[:4] == b"%PDF"


def decide_action(cached_hash, new_hash, block_present):
    """Decide what to do with a freshly downloaded PDF.

    Returns one of:
      "ocr"    -> content is new or changed; run OCR.
      "reheal" -> hash unchanged but the OCR block is missing from the markdown;
                  re-insert cached text, NO OCR.
      "skip"   -> hash unchanged and block already present; do nothing.
    """
    if cached_hash is None or cached_hash != new_hash:
        return "ocr"
    if not block_present:
        return "reheal"
    return "skip"


def _markers(pdf_url: str):
    return (f"<!-- OCR-PDF-START {pdf_url} -->", f"<!-- OCR-PDF-END {pdf_url} -->")


def build_ocr_block(pdf_url: str, ocr_text: str) -> str:
    """Wrap one PDF's OCR text in idempotent, URL-keyed markers."""
    start, end = _markers(pdf_url)
    return (
        f"\n\n{start}\n{OCR_HUMAN_TAG}\n"
        f"Document Source: {pdf_url}\n{ocr_text}\n{end}\n"
    )


def block_present(markdown: str, pdf_url: str) -> bool:
    if not markdown:
        return False
    start, _ = _markers(pdf_url)
    return start in markdown


def replace_ocr_block(markdown: str, pdf_url: str, new_block: str) -> str:
    """Idempotently insert/replace this PDF's OCR block.

    If a block for `pdf_url` already exists (matched by its markers) it is
    removed first, then the new block is appended. This is what stops re-runs
    from duplicating OCR text into `ocr_markdown`.
    """
    markdown = markdown or ""
    start, end = _markers(pdf_url)
    # Non-greedy removal of any existing block, including surrounding whitespace.
    pattern = re.compile(
        r"\n*" + re.escape(start) + r".*?" + re.escape(end) + r"\n*",
        re.DOTALL,
    )
    cleaned = pattern.sub("", markdown)
    return cleaned + new_block


def find_ocr_split_index(markdown: str):
    """Return the index in `markdown` where OCR-appended content begins, or
    None if no OCR markers are present.

    Recognizes both marker styles that have ever been written into
    `crawled_data.raw_markdown`:
      * legacy plain tag   -- OCR_HUMAN_TAG (no per-PDF boundary)
      * hash-aware markers -- "<!-- OCR-PDF-START ..." (always precedes the
        human tag within its own block, per `build_ocr_block`)
    Takes the earliest match so multiple concatenated legacy appends are all
    captured as one OCR suffix.
    """
    if not markdown:
        return None
    candidates = [
        idx
        for idx in (markdown.find(OCR_HUMAN_TAG), markdown.find("<!-- OCR-PDF-START"))
        if idx != -1
    ]
    return min(candidates) if candidates else None


def split_markdown_ocr(markdown: str):
    """Split a `raw_markdown` value into (base_markdown, ocr_markdown).

    `ocr_markdown` is None if no OCR content is present. Used by the one-time
    migration to pull legacy OCR text out of `crawled_data.raw_markdown` into
    `crawled_data_ocr`.
    """
    idx = find_ocr_split_index(markdown)
    if idx is None:
        return markdown, None
    base = markdown[:idx].rstrip()
    ocr = markdown[idx:].strip()
    return base, (ocr or None)


# ==========================================
# 3. DATABASE LAYER
# ==========================================
def ensure_cache_table(conn, cache_table: str = None):
    cache_table = cache_table or CACHE_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {cache_table} (
                pdf_url      TEXT PRIMARY KEY,
                page_url     TEXT,
                pdf_hash     TEXT NOT NULL,
                ocr_text     TEXT,
                last_checked TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{cache_table}_page ON {cache_table} (page_url);"
        )
    conn.commit()


def is_url_cached(conn, pdf_url: str, cache_table: str = None) -> bool:
    """True if this PDF URL is already in the cache. Used by URL_SKIP_MODE to
    skip immutable/content-addressed PDFs before downloading them."""
    cache_table = cache_table or CACHE_TABLE
    with conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {cache_table} WHERE pdf_url = %s;", (pdf_url,))
        return cur.fetchone() is not None


def get_cache_entry(conn, pdf_url: str, cache_table: str = None):
    """Return (pdf_hash, ocr_text) for a PDF, or None if uncached."""
    cache_table = cache_table or CACHE_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT pdf_hash, ocr_text FROM {cache_table} WHERE pdf_url = %s;",
            (pdf_url,),
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else None


def touch_cache_entry(conn, pdf_url: str, cache_table: str = None):
    """Bump last_checked without changing content (used on a skip)."""
    cache_table = cache_table or CACHE_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {cache_table} SET last_checked = NOW() WHERE pdf_url = %s;",
            (pdf_url,),
        )
    conn.commit()


def upsert_cache_entry(conn, pdf_url, page_url, pdf_hash, ocr_text,
                       cache_table: str = None):
    cache_table = cache_table or CACHE_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {cache_table} (pdf_url, page_url, pdf_hash, ocr_text,
                                       last_checked, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (pdf_url) DO UPDATE SET
                page_url     = EXCLUDED.page_url,
                pdf_hash     = EXCLUDED.pdf_hash,
                ocr_text     = EXCLUDED.ocr_text,
                last_checked = NOW(),
                updated_at   = NOW();
            """,
            (pdf_url, page_url, pdf_hash, ocr_text),
        )
    conn.commit()


def get_markdown(conn, page_url: str, crawled_table: str = None):
    crawled_table = crawled_table or CRAWLED_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT raw_markdown FROM {crawled_table} WHERE url = %s;",
            (page_url,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def set_markdown(conn, page_url: str, markdown: str,
                 crawled_table: str = None):
    crawled_table = crawled_table or CRAWLED_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {crawled_table} SET raw_markdown = %s WHERE url = %s;",
            (markdown, page_url),
        )
    conn.commit()


def page_exists(conn, page_url: str, crawled_table: str = None) -> bool:
    crawled_table = crawled_table or CRAWLED_TABLE
    with conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {crawled_table} WHERE url = %s;", (page_url,))
        return cur.fetchone() is not None


def ensure_ocr_table(conn, ocr_table: str = None):
    """The OCR portion of a page, kept separate from `crawled_data.raw_markdown`.

    No hard FOREIGN KEY to `crawled_data(url)` -- the table name is
    caller-configurable (tests use throwaway names), and enforcing it would
    tie DROP ordering across two dynamically named tables. The relationship
    is logical (same `url` values), guarded at write time by `page_exists`.
    """
    ocr_table = ocr_table or OCR_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ocr_table} (
                url          TEXT PRIMARY KEY,
                ocr_markdown TEXT,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
    conn.commit()


def get_ocr_markdown(conn, page_url: str, ocr_table: str = None):
    ocr_table = ocr_table or OCR_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT ocr_markdown FROM {ocr_table} WHERE url = %s;", (page_url,)
        )
        row = cur.fetchone()
    return row[0] if row else None


def set_ocr_markdown(conn, page_url: str, ocr_markdown: str,
                     ocr_table: str = None):
    ocr_table = ocr_table or OCR_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {ocr_table} (url, ocr_markdown, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (url) DO UPDATE SET
                ocr_markdown = EXCLUDED.ocr_markdown,
                updated_at   = NOW();
            """,
            (page_url, ocr_markdown),
        )
    conn.commit()


# ---- Targeted work-list (the fixed set of PDFs to OCR) --------------------
def ensure_targets_table(conn, targets_table: str = None):
    targets_table = targets_table or TARGETS_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {targets_table} (
                pdf_url    TEXT PRIMARY KEY,
                page_url   TEXT NOT NULL,
                status     VARCHAR(20) DEFAULT 'pending',
                attempts   INT DEFAULT 0,
                added_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        # Idempotent add for tables created before `attempts` existed.
        cur.execute(f"ALTER TABLE {targets_table} ADD COLUMN IF NOT EXISTS attempts INT DEFAULT 0;")
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{targets_table}_status "
            f"ON {targets_table} (status);"
        )
    conn.commit()


def add_target(conn, pdf_url, page_url, targets_table: str = None):
    targets_table = targets_table or TARGETS_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {targets_table} (pdf_url, page_url, status)
                VALUES (%s, %s, 'pending')
                ON CONFLICT (pdf_url) DO NOTHING;""",
            (pdf_url, page_url),
        )
    conn.commit()


def fetch_pending_targets(conn, targets_table: str = None):
    """Return [(pdf_url, page_url), ...] still needing OCR."""
    targets_table = targets_table or TARGETS_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT pdf_url, page_url FROM {targets_table}
                WHERE status IN ('pending', 'processing')
                ORDER BY added_at;"""
        )
        return cur.fetchall()


def mark_target(conn, pdf_url, status, targets_table: str = None):
    targets_table = targets_table or TARGETS_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {targets_table} SET status = %s, updated_at = NOW() "
            f"WHERE pdf_url = %s;",
            (status, pdf_url),
        )
    conn.commit()


def reset_stale_targets(conn, targets_table: str = None):
    """Any 'processing' rows left by a crashed run go back to 'pending'."""
    targets_table = targets_table or TARGETS_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {targets_table} SET status = 'pending' WHERE status = 'processing';"
        )
    conn.commit()


def record_target_failure(conn, pdf_url, permanent=False, targets_table: str = None):
    """Handle a target that didn't OCR.

    permanent=True  -> terminal 'failed' (e.g. the bytes aren't a valid PDF).
    permanent=False -> transient (download/vLLM error, empty OCR): increment
      attempts and requeue as 'pending' until MAX_OCR_ATTEMPTS is hit, then
      'failed'. This is what makes a power-cut / outage self-healing instead of
      burning the whole work-list to 'failed'.

    Returns the new status.
    """
    targets_table = targets_table or TARGETS_TABLE
    with conn.cursor() as cur:
        if permanent:
            cur.execute(
                f"UPDATE {targets_table} SET status='failed', attempts=attempts+1, "
                f"updated_at=NOW() WHERE pdf_url=%s;",
                (pdf_url,),
            )
            new_status = "failed"
        else:
            cur.execute(
                f"""UPDATE {targets_table}
                    SET attempts = attempts + 1,
                        status = CASE WHEN attempts + 1 >= %s THEN 'failed' ELSE 'pending' END,
                        updated_at = NOW()
                    WHERE pdf_url = %s
                    RETURNING status;""",
                (MAX_OCR_ATTEMPTS, pdf_url),
            )
            row = cur.fetchone()
            new_status = row[0] if row else "pending"
    conn.commit()
    return new_status


def vllm_healthy(timeout=8.0):
    """True if the vLLM OCR server answers. Checked at fleet startup so we never
    process (and mass-fail) the work-list while the model is down."""
    try:
        r = httpx.get(f"{VLLM_API_BASE}/models", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def apply_ocr_block(conn, page_url, pdf_url, ocr_text,
                    ocr_table: str = None, crawled_table: str = None):
    """Read-modify-write `crawled_data_ocr.ocr_markdown`, replacing this PDF's
    block. Never touches `crawled_data.raw_markdown`."""
    if not page_exists(conn, page_url, crawled_table):
        return False  # page row vanished; nothing to attach OCR text to
    current = get_ocr_markdown(conn, page_url, ocr_table) or ""
    new_block = build_ocr_block(pdf_url, ocr_text)
    updated = replace_ocr_block(current, pdf_url, new_block)
    set_ocr_markdown(conn, page_url, updated, ocr_table)
    return True


def fetch_targeted_urls(conn, crawled_table: str = None):
    crawled_table = crawled_table or CRAWLED_TABLE
    all_keywords = []
    for kws in TOPIC_KEYWORDS.values():
        all_keywords.extend(kws)
    like_conditions = " OR ".join(["raw_markdown ILIKE %s" for _ in all_keywords])
    params = [f"%{kw}%" for kw in all_keywords]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT url FROM {crawled_table} WHERE {like_conditions};", params
        )
        return [r[0] for r in cur.fetchall()]


# ==========================================
# 4. CORE PDF DECISION  (injectable OCR -> unit tested)
# ==========================================
async def handle_pdf(conn, page_url, pdf_url, pdf_bytes, ocr_func):
    """The heart of the change-detection logic for a single PDF.

    `ocr_func(pdf_bytes) -> str` is injected so tests can run without a GPU.
    Returns the action taken: "ocr" | "reheal" | "skip" | "invalid".
    All DB work is offloaded to threads to stay async-friendly.
    """
    if not is_valid_pdf(pdf_bytes):
        return "invalid"

    new_hash = compute_pdf_hash(pdf_bytes)
    cached = await asyncio.to_thread(get_cache_entry, conn, pdf_url)
    cached_hash = cached[0] if cached else None
    cached_text = cached[1] if cached else None

    ocr_markdown = await asyncio.to_thread(get_ocr_markdown, conn, page_url)
    present = block_present(ocr_markdown, pdf_url)

    action = decide_action(cached_hash, new_hash, present)

    if action == "skip":
        await asyncio.to_thread(touch_cache_entry, conn, pdf_url)
        return "skip"

    if action == "reheal":
        # Hash unchanged but block missing. If we have cached text, restore it
        # (no OCR). If the cache holds empty text (an unreadable PDF we already
        # gave up on), there is nothing to restore -> treat as a plain skip so
        # we don't keep churning on it every restart.
        await asyncio.to_thread(touch_cache_entry, conn, pdf_url)
        if cached_text:
            await asyncio.to_thread(
                apply_ocr_block, conn, page_url, pdf_url, cached_text
            )
            return "reheal"
        return "skip"

    # action == "ocr": content is new or changed.
    ocr_text = await ocr_func(pdf_bytes)
    if not ocr_text or not ocr_text.strip():
        # No text produced (vLLM blip / unreadable page). Do NOT cache and do NOT
        # mark success -- signal the caller so it can retry (targeted mode) rather
        # than silently recording an empty result as done.
        return "ocr_empty"
    await asyncio.to_thread(apply_ocr_block, conn, page_url, pdf_url, ocr_text)
    await asyncio.to_thread(
        upsert_cache_entry, conn, pdf_url, page_url, new_hash, ocr_text
    )
    return "ocr"


# ==========================================
# 5. VISION LLM PIPELINE  (production OCR implementation)
# ==========================================
def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85)
    out = base64.b64encode(buffered.getvalue()).decode("utf-8")
    buffered.close()
    return out


async def perform_ocr(base64_image):
    system_prompt = (
        "You are an expert OCR system. Extract all text from this image exactly "
        "as it appears. The text is primarily in Bengali. Do not add any "
        "conversational filler, explanations, or markdown blocks. Just return "
        "the raw extracted text."
    )
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the text from this document page:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""


async def vision_ocr(pdf_bytes: bytes) -> str:
    """Production OCR: rasterize the WHOLE PDF and OCR every page via vLLM."""
    extracted_text = ""
    try:
        # No page cap -- convert all pages of the document.
        pages = await asyncio.to_thread(convert_from_bytes, pdf_bytes)
        for i, page_image in enumerate(pages):
            base64_img = image_to_base64(page_image)
            page_text = await perform_ocr(base64_img)
            if page_text:
                extracted_text += f"\n--- Page {i + 1} ---\n{page_text}\n"
            page_image.close()
            await asyncio.sleep(4.0)  # Thermal safety cooldown
    except Exception as e:
        print(f"\n[!] PDF Conversion Error: {e}")
    return extracted_text


# ==========================================
# 6. WORKER POOL ARCHITECTURE
# ==========================================
def log_checkpoint(url):
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{url}\n")


async def network_scout_worker(network_queue, gpu_queue, http_client):
    while True:
        url = await network_queue.get()
        try:
            pdf_links = []
            timeout = httpx.Timeout(8.0, connect=4.0, read=4.0, pool=4.0)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Connection": "close",
            }
            response = await http_client.get(
                url, headers=headers, timeout=timeout, follow_redirects=True
            )
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code == 200 and "text/html" in content_type:
                if len(response.text) < MAX_HTML_BYTES:
                    soup = BeautifulSoup(response.text, "html.parser")
                    for a_tag in soup.find_all("a", href=True):
                        if a_tag["href"].lower().endswith(".pdf"):
                            pdf_links.append(urljoin(url, a_tag["href"]))
            pdf_links = list(set(pdf_links))
            if pdf_links:
                await gpu_queue.put((url, pdf_links))
            else:
                log_checkpoint(url)
                pbar.update(1)
        except Exception:
            log_checkpoint(url)
            pbar.update(1)
        finally:
            network_queue.task_done()


async def gpu_processing_worker(gpu_queue, http_client, conn):
    while True:
        page_url, pdf_links = await gpu_queue.get()
        for pdf_url in pdf_links:
            try:
                # URL-presence gate: skip an already-known (immutable) PDF URL
                # without downloading or OCRing it.
                if URL_SKIP_MODE and await asyncio.to_thread(
                    is_url_cached, conn, pdf_url
                ):
                    continue
                pdf_response = await http_client.get(
                    pdf_url, timeout=25.0, follow_redirects=True
                )
                if pdf_response.status_code != 200:
                    continue
                pdf_bytes = pdf_response.content
                del pdf_response
                await handle_pdf(conn, page_url, pdf_url, pdf_bytes, vision_ocr)
                del pdf_bytes
            except Exception:
                continue
        log_checkpoint(page_url)
        pbar.update(1)
        gpu_queue.task_done()
        gc.collect()


# ==========================================
# 7. ORCHESTRATOR
# ==========================================
async def run_fleet():
    global pbar
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)

    print("🚀 Initializing Hash-Aware PDF OCR Fleet (change detection ON)...")

    setup_conn = psycopg2.connect(**DB_CONFIG)
    ensure_cache_table(setup_conn)
    ensure_ocr_table(setup_conn)

    processed_urls = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            processed_urls = set(line.strip() for line in f)

    all_targeted = fetch_targeted_urls(setup_conn)
    setup_conn.close()
    pending_urls = [u for u in all_targeted if u not in processed_urls]

    print(
        f"📊 Target URLs: {len(all_targeted)} | Checkpointed: {len(processed_urls)} "
        f"| Pending: {len(pending_urls)}"
    )
    if not pending_urls:
        print("✅ Nothing pending. Fleet shutting down.")
        return

    network_queue = asyncio.Queue()
    gpu_queue = asyncio.Queue()
    for url in pending_urls:
        network_queue.put_nowait(url)

    # Each GPU worker gets its own dedicated connection (psycopg2 conns are not
    # safe to share across concurrent coroutines).
    gpu_conns = [psycopg2.connect(**DB_CONFIG) for _ in range(NUM_GPU_WORKERS)]

    print(
        f"⚡ Launching: {NUM_NETWORK_WORKERS} scouts, {NUM_GPU_WORKERS} GPU workers..."
    )
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    pbar = tqdm(total=len(pending_urls), desc="Hash-Aware OCR")

    async with httpx.AsyncClient(verify=False, limits=limits, follow_redirects=True) as http_client:
        scout_tasks = [
            asyncio.create_task(network_scout_worker(network_queue, gpu_queue, http_client))
            for _ in range(NUM_NETWORK_WORKERS)
        ]
        gpu_tasks = [
            asyncio.create_task(gpu_processing_worker(gpu_queue, http_client, gpu_conns[i]))
            for i in range(NUM_GPU_WORKERS)
        ]
        await network_queue.join()
        await gpu_queue.join()
        for task in scout_tasks + gpu_tasks:
            task.cancel()

    for c in gpu_conns:
        c.close()
    pbar.close()
    print("\n🎉 Hash-Aware OCR Fleet run complete.")


# ==========================================
# 8. TARGETED FLEET  (current strategy: OCR a fixed PDF list)
# ==========================================
async def targeted_ocr_worker(target_queue, http_client, conn):
    """Download + OCR one target PDF, write it to crawled_data_ocr (keyed by its
    page_url), and mark the target done/failed. No page scouting -- the PDF URLs
    are already known from the targets table."""
    while True:
        pdf_url, page_url = await target_queue.get()
        try:
            resp = await http_client.get(pdf_url, timeout=25.0, follow_redirects=True)
            if resp.status_code != 200:
                # HTTP problem -> transient, retry later.
                await asyncio.to_thread(record_target_failure, conn, pdf_url, False)
            else:
                pdf_bytes = resp.content
                del resp
                action = await handle_pdf(conn, page_url, pdf_url, pdf_bytes, vision_ocr)
                del pdf_bytes
                if action == "invalid":
                    # Not a valid PDF -> permanent failure, don't retry.
                    await asyncio.to_thread(record_target_failure, conn, pdf_url, True)
                elif action == "ocr_empty":
                    # No text produced (vLLM blip / blank page) -> retry.
                    await asyncio.to_thread(record_target_failure, conn, pdf_url, False)
                else:  # "ocr" | "reheal" | "skip" -> real text present
                    await asyncio.to_thread(mark_target, conn, pdf_url, "done")
        except Exception:
            # Download/connection/vLLM exception -> transient, retry later.
            await asyncio.to_thread(record_target_failure, conn, pdf_url, False)
        finally:
            pbar.update(1)
            target_queue.task_done()
            gc.collect()


async def run_targeted_fleet():
    """OCR exactly the PDFs listed in TARGETS_TABLE (current strategy)."""
    global pbar
    print("🎯 Initializing TARGETED PDF OCR Fleet (fixed PDF work-list)...")

    # Guard: never process the work-list while the OCR model is down -- otherwise
    # every PDF fails and (previously) got burned to 'failed'. Abort cleanly.
    if not vllm_healthy():
        print(f"[!] vLLM OCR server at {VLLM_API_BASE} is not responding. "
              f"Aborting so targets are not mass-failed. Start qwen36 and re-run.")
        return

    setup_conn = psycopg2.connect(**DB_CONFIG)
    ensure_cache_table(setup_conn)
    ensure_ocr_table(setup_conn)
    ensure_targets_table(setup_conn)

    # Auto-refresh the work-list: pick up citizen-charter PDFs discovered by the
    # latest re-crawl and append the new ones (idempotent; existing 'done'
    # targets are left as-is). Lazy import avoids a circular import.
    if AUTO_SEED:
        try:
            import seed_citizen_charter_targets as _seeder
            print("🔄 Auto-seeding targets from latest crawl (new citizen-charter PDFs)...")
            _seeder.run(dry_run=False)
        except Exception as e:
            print(f"[!] Auto-seed skipped ({e.__class__.__name__}: {e}). "
                  f"Proceeding with existing targets.")

    reset_stale_targets(setup_conn)
    targets = fetch_pending_targets(setup_conn)
    setup_conn.close()

    print(f"📊 Pending target PDFs: {len(targets)}")
    if not targets:
        print("✅ No pending target PDFs. Nothing to do.")
        return

    target_queue = asyncio.Queue()
    for t in targets:
        target_queue.put_nowait(t)

    gpu_conns = [psycopg2.connect(**DB_CONFIG) for _ in range(NUM_GPU_WORKERS)]
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    pbar = tqdm(total=len(targets), desc="Targeted OCR")

    print(f"⚡ Launching: {NUM_GPU_WORKERS} GPU OCR workers...")
    async with httpx.AsyncClient(verify=False, limits=limits, follow_redirects=True) as http_client:
        tasks = [
            asyncio.create_task(targeted_ocr_worker(target_queue, http_client, gpu_conns[i]))
            for i in range(NUM_GPU_WORKERS)
        ]
        await target_queue.join()
        for t in tasks:
            t.cancel()

    for c in gpu_conns:
        c.close()
    pbar.close()
    print("\n🎉 Targeted OCR Fleet run complete.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="PDF OCR fleet. Default: OCR the fixed target list "
                    "(pdf_ocr_targets). Use --scan for the legacy topic-keyword "
                    "page scan."
    )
    ap.add_argument(
        "--scan", action="store_true",
        help="Legacy mode: discover PDFs by scanning topic-keyword pages "
             "instead of using the fixed target work-list.",
    )
    ap.add_argument(
        "--deep", action="store_true",
        help="(--scan only) full content-hash verification instead of URL-skip.",
    )
    ap.add_argument(
        "--no-seed", action="store_true",
        help="Targeted mode: skip the auto-seed refresh; OCR only what's already "
             "in pdf_ocr_targets.",
    )
    args = ap.parse_args()
    if args.scan:
        URL_SKIP_MODE = not args.deep
        print(f"[*] Legacy scan mode: {'CONTENT-HASH' if args.deep else 'URL-SKIP'}")
        asyncio.run(run_fleet())
    else:
        AUTO_SEED = not args.no_seed
        print(f"[*] Targeted mode: OCR the PDFs in pdf_ocr_targets "
              f"(auto-seed {'OFF' if args.no_seed else 'ON'}).")
        asyncio.run(run_targeted_fleet())
