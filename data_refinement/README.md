# Data Refinement

Post-crawl enrichment for the GovBD dataset. The crawler
(`crawler_with_router/`) fills `crawled_data.raw_markdown` with each page's HTML
converted to markdown. This stage extracts **OCR text from the PDFs attached to
those pages**, stores it in a **separate table** (`crawled_data_ocr`), and builds
the structured dataset.

- **Database:** PostgreSQL `gov_spider_db`.
- **OCR model:** Qwen3.6 served by vLLM at `http://localhost:5000/v1` (model
  name `qwen36`).
- **Runtime:** use the `Bionotes_project` conda env — it has the full dependency
  set (`crawl4ai`, `httpx`, `bs4`, `openai`, `pdf2image`, `psycopg2`, `tqdm`,
  `transformers`):
  `/home/vpatest/miniconda3/envs/Bionotes_project/bin/python <script>.py`

---

## Current OCR strategy: targeted citizen-charter PDFs

OCR is **targeted**, not a blanket scan. We OCR only the PDFs on
**citizen-charter** pages (URLs matching `%citizen%charter%`), **filtered by
content freshness**: a PDF is kept only if it appears on a page whose
`কনটেন্টটি শেষ হাল-নাগাদ করা হয়েছে:` ("content last updated") date is on/after
`CONTENT_DATE_CUTOFF` (currently **2024-09-01**). Pages with no parseable content
date are excluded. This trims the raw ~1,709 charter PDFs to ~1,358. The
surviving PDF URLs live in a work-list table, `pdf_ocr_targets`, and the fleet
OCRs whatever is `pending` there.

> Note: the filter uses the **`কনটেন্টটি`** (content) date, *not* the volatile
> **`সাইটটি`** (site) timestamp that changes on every page render.

```
crawled_data (page markdown, incl. PDF links)
      │
      │  seed_citizen_charter_targets.py   (also auto-run by the fleet)
      ▼
pdf_ocr_targets (pdf_url → page_url, status)     ← the work-list
      │
      │  hash_aware_ocr_fleet.py   (download → OCR via vLLM)
      ▼
crawled_data_ocr (url, ocr_markdown)             ← OCR output, keyed by PAGE url
```

**OCR text is NOT written into `crawled_data.raw_markdown`.** It goes to its own
table `crawled_data_ocr`, keyed by the page URL. Each PDF's text is wrapped in
URL-keyed markers so re-runs replace a PDF's block in place instead of
duplicating it:

```
<!-- OCR-PDF-START https://…/doc.pdf -->
### [OCR EXTRACTED FROM ATTACHED PDF] ###
Document Source: https://…/doc.pdf
<extracted text>
<!-- OCR-PDF-END https://…/doc.pdf -->
```

### Monthly workflow (2 commands)

```bash
# 1. Re-crawl the gov sites (updates crawled_data with new/changed pages)
cd ../crawler_with_router && bash launch_fleet.sh

# 2. OCR: auto-seeds any newly-discovered charter PDFs, then OCRs the pending ones
cd ../data_refinement && python hash_aware_ocr_fleet.py
```

Step 2 **auto-seeds** first: it re-scans `crawled_data` for citizen-charter PDFs,
applies the content-date filter (≥ `CONTENT_DATE_CUTOFF`), and appends new
qualifying ones to `pdf_ocr_targets` (idempotent — existing `done` targets are
left alone), then OCRs everything `pending` and marks each `done`/`failed`.
Because the PDF URLs are content-addressed (immutable), a *changed* charter
appears at a *new* URL → new target → OCR'd; unchanged ones are never redone.
Change the cutoff via `CONTENT_DATE_CUTOFF` in `seed_citizen_charter_targets.py`.

Flags: `--no-seed` (skip the auto-seed refresh) · `--scan` (legacy mode, below).

---

## Scripts

### OCR (current)
| File | Purpose |
|------|---------|
| `hash_aware_ocr_fleet.py` | **The OCR fleet.** Default = *targeted* mode: auto-seed → OCR the `pending` PDFs in `pdf_ocr_targets` → write to `crawled_data_ocr`. `--scan` runs the legacy topic-keyword page crawl with content-hash / URL-skip change detection. |
| `seed_citizen_charter_targets.py` | Populate `pdf_ocr_targets` with citizen-charter PDFs found in `crawled_data`. Idempotent; run standalone or let the fleet auto-run it. |
| `migrate_split_ocr_table.py` | One-time migration that split legacy OCR text out of `crawled_data.raw_markdown` into `crawled_data_ocr`. |
| `seed_pdf_cache_from_existing.py` | Rebuild `pdf_ocr_cache` from already-OCR'd text (URL-skip seeding) — used by the legacy `--scan` incremental flow. |

### Legacy OCR (superseded, kept for reference / fallback)
| File | Purpose |
|------|---------|
| `vision_ocr_fleet.py` | Original first-pass OCR fleet; scanned topic-keyword pages and appended OCR into `raw_markdown`. |
| `sweep_stragglers_fleet.py` | Recovery pass for rows the first pass dropped. |

### Analysis / dataset
| File | Purpose |
|------|---------|
| `check_ocr_quality.py` | Reports OCR/gazette coverage — quick progress monitor. |
| `preflight_url_check.py` | Estimates OCR workload per topic before a run. |
| `extract_gazettes.py` | Downloads gazette PDFs into `Extracted_Gazettes/`. |
| `schema_generator.py` | Uses vLLM to build the structured `Master_Dataset_Enhanced.csv`. |
| `rnd_token_stats.py` | R&D: per-row LLM token-size distribution (raw_markdown vs ocr_markdown) using the exact Qwen tokenizer; writes `rnd_token_stats.json`. |
| `rnd_token_report.py` | Renders that JSON into `rnd_token_report.html` (charts + stats). |

### Tests (no GPU/vLLM needed; throwaway tables, production untouched)
| File | Covers |
|------|--------|
| `test_hash_aware_ocr.py` | Hash logic, change detection, OCR-table separation, the split migration. |
| `test_seed_pdf_cache.py` | `pdf_ocr_cache` seeding + URL-skip gate. |
| `test_targeted_ocr.py` | Target extraction, `pdf_ocr_targets` lifecycle, end-to-end target→OCR. |
| `test_vision_ocr.py` | Single-PDF smoke test for the vLLM OCR path. |

Run a suite: `python test_targeted_ocr.py` (etc.). All use a stub OCR and
`*_test_<pid>` tables.

---

## Tables

| Table | Role |
|-------|------|
| `crawled_data` | Page content (`raw_markdown`) — written by the crawler, read here. |
| `crawled_data_ocr` | `(url, ocr_markdown, updated_at)` — OCR output, keyed by page URL. |
| `pdf_ocr_targets` | `(pdf_url PK, page_url, status)` — the fixed OCR work-list (`pending`/`processing`/`done`/`failed`). |
| `pdf_ocr_cache` | `(pdf_url PK, page_url, pdf_hash, ocr_text, …)` — per-PDF hash cache; skips re-OCR of unchanged PDFs. |

---

## Legacy `--scan` mode (content-hash change detection)

`python hash_aware_ocr_fleet.py --scan` runs the original approach: crawl the
topic-keyword pages (NID, Birth/Death, Trade License, Land, Passport,
Vehicle/License, Utility Bills, Health), discover PDF links, and OCR them with
change detection:

| Situation | Action |
|-----------|--------|
| New PDF | OCR, cache hash + text |
| Unchanged (URL already cached, or hash match) | skip |
| Changed bytes (`--deep`) | re-OCR, replace block |

`--deep` forces full content-hash verification (download + SHA-256 every PDF)
instead of the default URL-presence skip.

---

## Dependencies

- Python 3.10+ (tested on 3.12) via the `Bionotes_project` conda env.
- `psycopg2`, `httpx`, `beautifulsoup4`, `openai`, `pdf2image`, `tqdm`,
  `transformers` (for the R&D tokenizer).
- A running vLLM server (`qwen36`) for OCR / schema generation.
- `poppler-utils` (for `pdf2image` rasterization).
