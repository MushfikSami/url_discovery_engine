# GovBD Crawler Fleet

A domain-by-domain web crawler fleet for Bangladesh government websites (`.gov.bd`). Discovers, parses, and stores clean markdown content into PostgreSQL — with aggressive trap detection and semantic sanitization.

## Architecture

```
seed_websites (domains)  ──▶  spider_queue (per-domain pages)  ──▶  crawled_data (clean markdown)
                                └── domain_hierarchy (map)
```

Each worker picks one pending domain, then crawls all pages within that domain before moving to the next. This prevents cross-domain contamination and makes failure recovery trivial.

## Files

| File | Purpose |
|------|---------|
| `db_setup.py` | Creates `gov_spider_db` and all tables |
| `spider.py` | Main crawler — URL filtering, fetching, parsing, queuing |
| `parsers.py` | Static (markdownify) and JS-rendered (crawl4ai) HTML-to-markdown |
| `extractor.py` | SPA detection, keyword extraction, snippet generation |
| `spider_trap_detector.py` | Analyzes DB for traps, duplicates, bloated domains |
| `db_query.py` | Runs SQL queries and exports results to text |
| `health_check.py` | Generates fleet health reports (speed, progress, errors) |
| `launch_fleet.sh` | Spawns N concurrent workers with per-worker log files |
| `strategy.md` | Full filter ruleset — URL traps, semantic sanitization, encoding checks |

## Database Schema

```sql
seed_websites      (website_url, status)                    -- .gov.bd domains to crawl
spider_queue       (url, base_domain, status, added_at)     -- pages per domain
domain_hierarchy   (website, web_pages[])                    -- crawl map
crawled_data       (url, raw_markdown, snippet, keywords[]) -- final output
```

## Quick Start

```bash
# 1. Initialize the database
python db_setup.py

# 2. Add domains to crawl (one URL per line)
# Edit data/crawled_alive_gov_bd_sites.txt

# 3. Launch 30 workers
chmod +x launch_fleet.sh
./launch_fleet.sh

# 4. Monitor progress
python health_check.py
tail -f crawler_logs/worker_1.log

# 5. Analyze results
python spider_trap_detector.py
```

## URL Filters

The crawler blocks infinite loops, CMS routing bugs, and RAG poison before downloading. Full ruleset in [strategy.md](strategy.md).

Key filter categories:
- **CMS routing mutations** — repeating path segments (`/home/home/`, `/notice/notice/`)
- **User-generated content** — profiles, photos, success stories
- **Infinite directories** — scouting member registries, factory inspection databases
- **Legacy databases** — bridge inspections, customs tariffs, .asp archives
- **Media & uploads** — `.jpg`, `.png`, `/wp-content/uploads/`
- **Pagination traps** — `page_name=ELibrary&page=23000`

## Payload Sanitization

After download, content is checked for:
- **Exact duplicates** — MD5 hash deduplication
- **Base64 image bloat** — documents >500K characters deleted
- **Empty pages** — <50 characters, placeholder text, boilerplate
- **Disguised errors** — 404s, access denied, Cloudflare bot checks
- **SEO defacement** — casino/crypto/viagra spam injection
- **Encoding failures** — mojibake, Latin-1 misinterpretation of Bengali

## Worker Configuration

Edit `NUM_WORKERS` in [launch_fleet.sh](launch_fleet.sh) to adjust concurrency. Each worker gets a log file in `crawler_logs/`. Workers are staggered by 0.5s to avoid database thundering herd.

## Dependencies

- Python 3.10+
- `psycopg2`, `httpx`, `beautifulsoup4`, `markdownify`, `crawl4ai`
