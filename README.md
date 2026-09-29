# URL Discovery Engine

Pipeline for discovering, crawling, and refining content from Bangladesh
government (`.gov.bd`) websites into a structured dataset.

The two active stages are **`crawler_with_router/`** (crawl the sites) and
**`data_refinement/`** (OCR the attached PDFs + build the dataset). They share one
PostgreSQL database, `gov_spider_db`.

```
 .gov.bd sites ──▶ crawler_with_router ──▶ crawled_data ──▶ data_refinement ──▶ crawled_data_ocr
                    (HTML → markdown)        (+ change          (targeted PDF        + Master dataset
                                              detection)         OCR via vLLM)
```

## Prerequisites

- **PostgreSQL** running with database `gov_spider_db` (config in
  `crawler_with_router/db_setup.py`).
- **Conda env `Bionotes_project`** — the only env with the full dependency set
  (`crawl4ai`, `httpx`, `bs4`, `openai`, `pdf2image`, `psycopg2`, `tqdm`,
  `transformers`). Run every script with it:
  ```bash
  /home/vpatest/miniconda3/envs/Bionotes_project/bin/python <script>.py
  # or: conda activate Bionotes_project
  ```
- **vLLM** serving Qwen3.6 at `http://localhost:5000/v1` (model `qwen36`) — needed
  for OCR and schema generation (not for crawling).
- **Chromium/Playwright** (bundled via crawl4ai) for JS-heavy pages, and
  `poppler-utils` for PDF rasterization.

## End-to-end run

```bash
# ── Stage 1: crawl the gov websites ───────────────────────────────
cd crawler_with_router
python db_setup.py                 # first time only: create tables
python migrate_add_content_hash.py # first time only: enable incremental re-crawl
bash launch_fleet.sh               # 30-worker crawl → fills/refreshes crawled_data

# ── Stage 2: OCR the attached PDFs + build the dataset ────────────
cd ../data_refinement
python hash_aware_ocr_fleet.py     # auto-seeds targets, OCRs pending → crawled_data_ocr
python schema_generator.py         # build Master_Dataset_Enhanced.csv
```

To **re-crawl later** (monthly refresh), just re-arm and relaunch:
```sql
-- in psql on gov_spider_db
UPDATE seed_websites SET status='pending';
UPDATE spider_queue  SET status='pending';
```
then `bash launch_fleet.sh`, then `python hash_aware_ocr_fleet.py` again.

---

## `crawler_with_router/` — the crawler

Domain-by-domain BFS crawler for `.gov.bd`. Seeds a domain, walks every in-domain
page from a persistent `spider_queue`, converts HTML→markdown (static via
markdownify, JS-heavy via headless crawl4ai), and stores clean content in
`crawled_data`. Heavy URL trap/spam filtering keeps the frontier finite.

**Incremental re-crawl (change detection):** after the first full crawl, re-crawls
only *rewrite* pages whose content changed — via HTTP `304`, a raw-HTML hash, and
a markdown hash (columns `content_hash`, `source_hash`, `http_etag`,
`last_checked`, `content_updated_at`). Run `migrate_add_content_hash.py` once to
add these columns + seed the baseline. Note: the portal injects a live
"last updated" timestamp and rarely sends ETags, so wall-clock stays fetch-bound
even though DB churn drops.

Key files: `spider.py` (crawler), `parsers.py` / `extractor.py` (HTML→markdown +
routing), `change_detection.py` (incremental logic), `launch_fleet.sh` (workers),
`health_check.py` / `spider_trap_detector.py` (monitoring),
`RECURSIVE_CRAWL_MECHANISM.md` (design write-up).
**See [`crawler_with_router/README.md`](crawler_with_router/README.md) for details.**

## `data_refinement/` — OCR + dataset

Extracts OCR text from PDFs attached to crawled pages and stores it in a
**separate** table `crawled_data_ocr` (keyed by page URL — it does **not** touch
`raw_markdown`).

**Current OCR strategy is targeted:** OCR only the **citizen-charter** PDFs
(`pdf_ocr_targets` work-list). `hash_aware_ocr_fleet.py` auto-seeds new charter
PDFs from the latest crawl, then OCRs the `pending` ones via vLLM. A per-PDF hash
cache (`pdf_ocr_cache`) prevents re-OCRing unchanged PDFs. A legacy `--scan` mode
crawls topic-keyword pages instead.

Key files: `hash_aware_ocr_fleet.py` (the fleet),
`seed_citizen_charter_targets.py` (targets), `migrate_split_ocr_table.py`
(one-time OCR→own-table migration), `schema_generator.py` (dataset),
`check_ocr_quality.py` (coverage), `rnd_token_*.py` (token-size R&D).
**See [`data_refinement/README.md`](data_refinement/README.md) for details.**

---

## Shared database (`gov_spider_db`)

| Table | Written by | Holds |
|-------|-----------|-------|
| `seed_websites` | crawler | domains to crawl + status |
| `spider_queue` | crawler | per-page crawl frontier + status |
| `crawled_data` | crawler | page `raw_markdown` + change-detection hashes |
| `crawled_data_ocr` | data_refinement | OCR text per page |
| `pdf_ocr_targets` | data_refinement | fixed PDF OCR work-list |
| `pdf_ocr_cache` | data_refinement | per-PDF hash cache |

## Testing

Both stages ship test suites that use stub OCR and throwaway `*_test_<pid>`
tables, so **no GPU/vLLM and no production data are touched**:

```bash
# crawler
cd crawler_with_router && python test_change_detection.py
# data refinement
cd ../data_refinement && python test_hash_aware_ocr.py && \
  python test_seed_pdf_cache.py && python test_targeted_ocr.py
```

## Other directories (experimental / adjacent, not part of this pipeline)

`recursive_crawler/`, `website_discovery/`, `WebRag/`, `wiki_entity/`,
`edirectory_crawler/`, `v4_retrieval_speed_test/` are separate experiments; each
has its own README where applicable.
