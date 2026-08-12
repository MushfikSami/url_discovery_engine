"""
hash_aware_ocr_fleet.py
=======================

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

CHECKPOINT_FILE = "data/hash_ocr_checkpoint.txt"
MAX_PAGES_PER_PDF = 30
NUM_NETWORK_WORKERS = 50
NUM_GPU_WORKERS = 3
MAX_PDF_BYTES = 50_000_000
MAX_HTML_BYTES = 2_000_000

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
        # Still record the hash so we don't keep re-OCRing an unreadable PDF.
        await asyncio.to_thread(
            upsert_cache_entry, conn, pdf_url, page_url, new_hash, ""
        )
        return "ocr"
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
    """Production OCR: rasterize the PDF and OCR each page via vLLM."""
    extracted_text = ""
    try:
        pages = await asyncio.to_thread(
            convert_from_bytes, pdf_bytes, first_page=1, last_page=MAX_PAGES_PER_PDF
        )
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


if __name__ == "__main__":
    asyncio.run(run_fleet())
