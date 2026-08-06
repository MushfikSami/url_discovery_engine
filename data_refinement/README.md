# Data Refinement

Post-crawl enrichment for the GovBD dataset. The crawler fleet
(`crawler_with_router/`) fills `crawled_data.raw_markdown` with HTML converted to
markdown. This stage augments those rows with **OCR text extracted from attached
PDFs**, extracts gazettes, checks OCR quality, and generates the structured
schema for the final dataset.

All scripts talk to the same PostgreSQL database (`gov_spider_db`) and OCR runs
against a local vLLM server (`http://localhost:5000/v1`, model `qwen36`).

## Pipeline at a glance

```
crawled_data (HTML→markdown)
      │
      ├── vision_ocr_fleet.py ........ OCR every targeted page's PDFs (first pass)
      ├── sweep_stragglers_fleet.py .. re-run only rows still missing OCR
      ├── hash_aware_ocr_fleet.py .... restart-safe: OCR only PDFs whose content changed
      │
      ▼
crawled_data.raw_markdown  (HTML markdown + appended OCR blocks)
      │
      ├── extract_gazettes.py ........ pull gazette PDFs out into files
      ├── check_ocr_quality.py ....... report OCR/gazette coverage
      └── schema_generator.py ........ build the structured Master Dataset
```

Only pages matching the service **topic keywords** (NID, Birth/Death, Trade
License, Land, Passport, Vehicle/License, Utility Bills, Health) are targeted, so
GPU time is spent on high-value documents.

## Scripts

| File | Purpose |
|------|---------|
| `vision_ocr_fleet.py` | First-pass OCR fleet. For every targeted page it scouts PDF links, downloads them, OCRs each page via vLLM, and appends the text to `raw_markdown`. Tracks progress with a URL checkpoint file. |
| `sweep_stragglers_fleet.py` | Recovery pass. Re-targets only rows that still lack the `[OCR EXTRACTED FROM ATTACHED PDF]` tag (dropped by timeouts/skips in the first pass). |
| `hash_aware_ocr_fleet.py` | **Restart-safe OCR with content-hash change detection** (see below). Re-runs skip PDFs whose bytes are unchanged. |
| `test_hash_aware_ocr.py` | Test suite for the hash-aware fleet. Runs with a stub OCR (no GPU) against throwaway tables (production data untouched). |
| `extract_gazettes.py` | Downloads gazette PDFs referenced in the data and saves them to `Extracted_Gazettes/`. |
| `check_ocr_quality.py` | Reports how many rows/PDFs/gazettes have OCR content — quick progress monitor. |
| `preflight_url_check.py` | Estimates the OCR workload per topic before launching a fleet. |
| `schema_generator.py` | Uses vLLM to turn enriched markdown into the structured `Master_Dataset_Enhanced.csv`. |
| `test_vision_ocr.py` | Single-PDF smoke test for the vLLM OCR path. |

## Hash-Aware OCR (restart-safe re-crawling)

`hash_aware_ocr_fleet.py` solves a problem in the older fleets: on restart they
track progress by URL only, so an unchanged PDF gets re-OCR'd from scratch — and
because they blindly append, the OCR text is duplicated into `raw_markdown`.

This fleet keeps a per-PDF **SHA-256 content hash** in a new `pdf_ocr_cache`
table. On every run each PDF is downloaded, hashed, and compared:

| Situation | Action | OCR runs? |
|-----------|--------|-----------|
| New PDF (not in cache) | OCR, cache the text + hash, append block | ✅ |
| Hash **unchanged** | Skip | ❌ |
| Hash **changed** | Re-OCR, replace that PDF's block in place, update cache | ✅ |
| Hash unchanged but block missing (row was re-crawled) | Restore text from cache | ❌ |

### Where the OCR data goes

Same row, same column — it does **not** create new rows. The OCR text is appended
to the existing `crawled_data.raw_markdown` (the HTML-derived markdown is kept),
matched on the **page URL**. Each PDF's text is wrapped in URL-keyed markers so a
re-run replaces its block instead of duplicating it:

```
<existing HTML → markdown content>

<!-- OCR-PDF-START https://site.gov.bd/doc.pdf -->
### [OCR EXTRACTED FROM ATTACHED PDF] ###
Document Source: https://site.gov.bd/doc.pdf
<extracted text>
<!-- OCR-PDF-END https://site.gov.bd/doc.pdf -->
```

The row must already exist (the crawler writes it first); if it's missing, the
PDF is skipped rather than inserted.

### `pdf_ocr_cache` table

Auto-created on first run.

```sql
pdf_ocr_cache (
    pdf_url      TEXT PRIMARY KEY,
    page_url     TEXT,
    pdf_hash     TEXT NOT NULL,   -- SHA-256 of the raw PDF bytes
    ocr_text     TEXT,            -- cached extraction, reused on reheal
    last_checked TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ
)
```

## Quick start

```bash
# 1. Estimate the workload (optional)
python preflight_url_check.py

# 2a. First full OCR pass
python vision_ocr_fleet.py

# 2b. OR restart-safe pass (recommended for re-crawls — skips unchanged PDFs)
python hash_aware_ocr_fleet.py

# 3. Recover any dropped rows
python sweep_stragglers_fleet.py

# 4. Check coverage
python check_ocr_quality.py

# 5. Build the structured dataset
python schema_generator.py
```

## Testing

The hash-aware fleet ships with a full test suite. It uses a stub OCR (no GPU or
vLLM required) and throwaway `*_test_<pid>` tables, so it never touches the
~140k-row production `crawled_data`:

```bash
python test_hash_aware_ocr.py
```

Covers hash determinism/sensitivity, unchanged→skip, changed→re-OCR + block
replacement (no duplication), new→OCR-once, reheal-without-OCR, invalid/oversize
rejection, empty-OCR handling, and multi-PDF isolation on one page.

## Dependencies

- Python 3.10+ (tested on 3.12)
- `psycopg2`, `httpx`, `beautifulsoup4`, `openai`, `pdf2image`, `tqdm`
- A running vLLM server for OCR / schema generation
- `poppler-utils` (for `pdf2image` rasterization)
