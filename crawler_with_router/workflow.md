# GovBD Crawler — Work System & Workflow

## Overview

A distributed domain-by-domain web crawler fleet that discovers, fetches, parses, and sanitizes markdown content from **39,752 Bangladesh government websites** (`.gov.bd`). The system processed **2.8 million pages** at ~475 pages/minute, storing nearly **3 million clean markdown documents** in PostgreSQL.

## High-Level Flow

```
seed_websites ──▶ spider_queue ──▶ process_url ──▶ save_crawled_data
     │                │                  │                   │
  domains       per-domain pages   URL filters +          clean markdown
  to crawl       (pending→done)     fetching + parsing     + snippet
                                                │
                                        parsers.py (markdownify
                                         or crawl4ai for JS)
```

Three data tables form the pipeline. One seed table feeds one queue table, which feeds one output table. Each worker handles exactly one domain at a time, preventing cross-domain contamination.

## Database Pipeline

```
┌─────────────────────────┐    ┌──────────────────────────┐    ┌────────────────────┐
│  seed_websites          │    │  spider_queue             │    │  crawled_data       │
│─────────────────────────│    │──────────────────────────│    │────────────────────│
│ website_url  (PK)       │    │ url            (PK)      │    │ url        (PK)     │
│ status                   │    │ base_domain              │    │ raw_markdown        │
│  pending / processing /  │    │ status                     │    │ snippet             │
│  completed               │    │  pending / processing /   │    │ keywords[]          │
│                          │    │  completed / failed       │    │                     │
└─────────────────────────┘    │ added_at                   │    └────────────────────┘
                               └──────────────────────────┘
                                        │
                                        ▼
                               ┌────────────────────┐
                               │  domain_hierarchy   │
                               │────────────────────│
                               │ website  (PK)       │
                               │ web_pages[]         │
                               └────────────────────┘
```

## Worker Lifecycle

```
Step 1: db_setup.py                          Step 2: launch_fleet.sh
    │                                              │
    ▼                                              ▼
CREATE DATABASE                            For i = 1 to NUM_WORKERS:
CREATE TABLE seed_websites                    nohup python spider.py
CREATE TABLE spider_queue          ──▶       > crawler_logs/worker_$i.log &
CREATE TABLE crawled_data                     stagger 0.5s between launches
CREATE TABLE domain_hierarchy
```

## Per-Worker Loop

Each `spider.py` worker runs two nested loops:

### Outer Loop — Domain Progression

```
while True:
    1. Claim one "pending" seed_websites row (skip-locked)
    2. Set status = "processing"
    3. If no pending seeds remain → break, shut down
    4. Seed the root URL into spider_queue for this domain
    5. Enter inner loop
```

### Inner Loop — Page Crawling

```
while True:
    1. Claim one "pending" spider_queue row for THIS domain only
    2. Set status = "processing"
    3. If no pages left → mark domain "completed", break inner loop
    4. Fetch URL → parse HTML → extract links → apply filters
    5. Convert HTML to markdown (static or JS-rendered)
    6. Save markdown to crawled_data
    7. Queue new discovered links as "pending"
    8. Set current page status = "completed" (or "failed")
    9. Sleep 0.5s
```

## URL Filtering (The Trap Killers)

Every discovered link passes through 19 filters before being queued. Links that fail any filter are silently dropped — never queued, never fetched.

| # | Filter | What It Blocks |
|---|--------|----------------|
| 0 | Radioactive Ghost | Cross-linked dictionary domains |
| 1 | Frankenstein Killer | Injected `<`, `>`, `{`, `[` in URLs |
| 2 | Infinite Loop Killer | URLs longer than 250 characters |
| 3 | Path Recursion | Repeated path segments (`/site/view/site/view/`) |
| 4 | nolink Bug | `nolink` template artifacts |
| 5 | Broken Spaces | Unencoded spaces or `%20` in URLs |
| 6 | Relative Domain | URLs containing `.gov.bd` or `.com` in the path |
| 7 | Media Galleries | `/photo`, `/gallery`, `/video`, `/image` |
| 8 | CMS Routing Loops | `/node/`, `/mlid/`, `/views/`, `/site/eservices/` |
| 9 | Application Traps | OPAC search/export, tracklinks, operative tariff |
| 10 | Search Pages | `/search/all/`, `search?`, `separator` |
| 11 | Separator Bug | `separator` in dropdown line artifacts |
| 12 | Session IDs | `;jsessionid=` tracking |
| 13 | Laravel Payloads | Encrypted Base64, passport/application routes |
| 14 | Cloudflare & OAuth | Bot challenges, OAuth code callbacks |
| 15 | Encrypted Routes & DBs | Massive exporter directories, edirectory listings |
| 16 | Print Views | Duplicate print-friendly pages |
| 17 | Media Extensions & Deep DBs | `.jpg`, `.png`, `/wp-content/uploads/`, bridge databases |
| 18 | CMS Deep Loops | Savar `/assesment_home/`, SREDA `/nem/` |
| 19 | UGC & Registries | Profiles, photos, success stories, factory audits, pagination traps |

See [strategy.md](strategy.md) for the full ruleset with target domains and rationale.

## HTML-to-Markdown Pipeline

```
                    is_javascript_heavy(soup)?
                           │
                    Yes ───┴─── No
                     │            │
                     ▼            ▼
            AsyncWebCrawler    markdownify
            (crawl4ai)         (BeautifulSoup + markdownify)
                 │                │
                 │ headless       │ strips script/style
                 │ browser        │ removes nav/footer/header
                 │ renders JS     │ ATX heading style
                 │ extracts MD    │ instant conversion
                 ▼                ▼
              markdown ───────────┘
                    │
                    ▼
          save_crawled_data()
          - Store raw_markdown
          - Generate snippet (first 250 chars)
          - Extract keywords (Bengali + English, top 50)
```

SPA detection ([extractor.py:5-26](extractor.py)):
- Fewer than 500 chars of visible text + more than 5 `<script>` tags → JS-heavy
- Root div (`#root`, `#app`, `#__next__`) exists but is empty → JS-heavy
- Otherwise → static, use markdownify

## Payload Sanitization (Post-Download)

After markdown is extracted, it passes semantic checks before being stored:

| Check | Rule | Action |
|-------|------|--------|
| Empty Shell | <50 characters of text | Delete |
| Placeholder Text | "Under Construction", "Site is being updated" | Delete |
| Disguised Errors | "404 Not Found", "Access Denied", "Cloudflare", "Database connection error" | Delete |
| Empty Tables | "No records found", "No data available in table" | Delete |
| SEO Defacement | "casino", "jackpot", "crypto", "viagra" (whitelist: `ti-bangladesh.org`) | Delete |
| Mojibake | `CHR(65533)`, `?????`, `à¦`, `à§` | Delete |
| Base64 Monsters | Document >500,000 characters | Delete |
| Exact Duplicates | MD5 hash match across URLs | Keep first, delete rest |
| Orphans | Markdown exists but URL no longer in queue | Delete |

## Fleet Operations

```
┌─────────────────────────────────────────────────────────┐
│                    launch_fleet.sh                       │
│                                                         │
│  NUM_WORKERS=30  ──▶  30 concurrent python spider.py   │
│                        staggered 0.5s apart              │
│                                                         │
│  worker_1.log  worker_2.log  ...  worker_30.log        │
│                                                         │
│  tail -f crawler_logs/worker_1.log  ──▶ live monitor   │
│                                                         │
│  python health_check.py  ──▶  reports/fleet_report_*.txt
└─────────────────────────────────────────────────────────┘
```

### Health Report Output

```
SPIDER FLEET DAILY REPORT - 2026-05-03 10:55

ROOT DOMAINS (seed_websites):
  - Completed:  39752
  - Processing: 0 (Active workers)
  - Pending:    0
  - Total:      39752

INTERNAL WEBPAGES (spider_queue):
  - Completed:  2807565
  - Failed:     345 (Dead links / Timeouts)
  - Pending:    0
  - Total Found:2807910

EXTRACTED DATA (crawled_data):
  - Clean Markdown Saved: 2969855 pages

FLEET PERFORMANCE:
  - Average Speed: 474.80 pages / minute
```

### Trap Detection

Run `spider_trap_detector.py` post-crawl to audit the database for:
- Top 10 bloated domains by page count
- URLs with query parameters (pagination trap candidates)
- Content duplication (same markdown under different URLs)

## Concurrency Model

- **Database**: `ThreadedConnectionPool(1, 10)` per worker — each worker has its own pool
- **Queue locking**: `FOR UPDATE SKIP LOCKED` — workers claim rows without blocking each other
- **Domain isolation**: `WHERE base_domain = %s` — inner loop only processes pages from the current domain
- **Inter-worker**: Independent — no shared memory, no cross-talk, just the shared PostgreSQL database

## Data Flow Summary

```
39,752 seed domains
      │
      ▼  (launch_fleet.sh spawns 30 workers)
      │
2,807,910 pages discovered in spider_queue
  - 2,807,565 completed successfully
  - 345 failed (dead links / timeouts)
      │
      ▼  (URL filters drop ~40% of discovered links before fetch)
      │
2,969,855 clean markdown documents in crawled_data
      │
      ▼  (post-download sanitization: dedup, error detection, encoding checks)
      │
Final dataset ready for LLM ingestion
```
