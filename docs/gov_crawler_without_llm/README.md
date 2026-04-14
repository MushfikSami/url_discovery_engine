# Gov BD Crawler (Without LLM)

## Overview

This module handles crawling and content extraction from Bangladesh government websites without AI enrichment. It stores crawled content in PostgreSQL for later processing or direct use.

---

## Files

| File | Purpose |
|------|---------|
| [`main.py`](main.py) | Pipeline orchestration |
| [`crawler.py`](crawler.py) | Async content extraction |
| [`database.py`](database.py) | PostgreSQL operations |
| [`loader.py`](loader.py) | URL loading from file |
| [`config.py`](config.py) | Configuration settings |

---

## main.py

### Purpose

Orchestrates the complete crawling pipeline.

### Execution Flow

```python
async def run_pipeline():
    1. setup_database()          # Ensure gov_bd_pages table exists
    2. load_urls_from_txt()      # Load URLs from crawled_alive_gov_bd_sites.txt
    3. process_pending_urls()    # Crawl all pending URLs
```

### Usage

```bash
cd gov_crawler_without_llm
python main.py
```

---

## database.py

### Purpose

Manages PostgreSQL database operations for the gov_bd_pages table.

### Database Schema

```sql
CREATE TABLE gov_bd_pages (
    url TEXT PRIMARY KEY,
    title TEXT,
    markdown_body TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    crawled_at TIMESTAMP
);
```

### Functions

| Function | Purpose |
|----------|---------|
| `get_connection()` | Return fresh DB connection |
| `setup_database()` | Create/verify gov_bd_pages table |
| `insert_pending_url(url)` | Add URL to queue (ON CONFLICT DO NOTHING) |
| `update_url_status(url, title, markdown, status)` | Update crawled content |
| `get_pending_urls()` | Return list of 'pending' URLs |

### Connection Settings

```python
DB_CONFIG = {
    "dbname": "gov_bd_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}
```

---

## loader.py

### Purpose

Loads URLs from a text file into the database queue.

### Key Function: `load_urls_from_txt()`

**Logic:**
```python
1. Open TARGET_FILE (crawled_alive_sites.txt)
2. Read line by line
3. Strip whitespace
4. Skip empty lines
5. Insert as 'pending' status
6. ON CONFLICT (url) DO NOTHING
```

### Configuration

```python
TARGET_FILE = "crawled_alive_sites.txt"
```

### Usage

Called automatically by `main.py` but can be commented out after first run to prevent re-reading.

---

## crawler.py

### Purpose

Async crawler that fetches and processes government website content.

### Key Features

- Uses `crawl4ai.AsyncWebCrawler`
- Excluded tags: nav, footer, header, aside, form, script, style, noscript
- Word count threshold: 20
- Politeness delay: 0.5 seconds between URLs

### Key Function: `clean_gov_bd_markdown(raw_md, title)`

**Purpose:** Remove a2i framework bloat from Bangladesh government sites.

**Junk Keywords Filtered:**
- "অফিসের ধরণ নির্বাচন করুন"
- "এক্সেসিবিলিটি মেনুতে যান"
- "বাংলাদেশ জাতীয় তথ্য বাতায়ন"
- "অফিস স্তর নির্বাচন করুন"
- "বিভাগ নির্বাচন করুন"
- "জেলা নির্বাচন করুন"
- "উপজেলা নির্বাচন করুন"
- "হটলাইন"
- "মেনু নির্বাচন করুন"
- "জরুরি সেবা নম্বরসমূহ"
- "ফন্ট বৃদ্ধি ফন্ট হ্রাস"
- "স্ক্রিন রিডার ডাউনলোড করুন"
- "© 2026 সর্বস্বত্ব সংরক্ষিত"
- "পরিকল্পনা এবং বাস্তবায়ন"

**Logic:**
```python
1. Split markdown into lines
2. Skip lines containing junk keywords
3. Stop processing at footer markers
4. Collapse multiple newlines to double newline
5. Return cleaned markdown
```

### Key Function: `process_pending_urls()`

**Flow:**
```python
1. Get all 'pending' URLs from database
2. For each URL:
   - AsyncWebCrawler.arun() with exclusions
   - On success: extract title + cleaned markdown
   - Update status to 'success'/'failed'/'error'
   - 0.5 second delay for politeness
```

---

## Configuration

### Database

| Setting | Value |
|---------|-------|
| Database | gov_bd_db |
| User | postgres |
| Password | password |
| Host | localhost |
| Port | 5432 |

### Crawler Settings

| Setting | Value |
|---------|-------|
| Excluded tags | nav, footer, header, aside, form, script, style, noscript |
| Word threshold | 20 |
| Politeness delay | 0.5s |
| Cache | False (first run) |

### Input File

```
crawled_alive_gov_bd_sites.txt
```

One URL per line, full HTTP/HTTPS URLs.

---

## Status Values

| Status | Meaning |
|--------|---------|
| `pending` | URL loaded, not yet crawled |
| `success` | Successfully crawled with content |
| `failed` | Crawler returned success=False |
| `error` | Exception during crawling |

---

## Data Flow

```mermaid
flowchart TD
    subgraph Input["Input"]
        Text["crawled_alive_sites.txt\n1 URL per line"]
    end

    subgraph Loader["URL Loading"]
        Loader["loader.py\nload_urls_from_txt()"]
    end

    subgraph Queue["Pending Queue"]
        DB1["PostgreSQL: gov_bd_pages\nstatus='pending'"]
    end

    subgraph Crawl["Content Crawling"]
        Crawler["crawler.py\nAsyncWebCrawler.arun()\n- Excluded tags\n- Word threshold\n- Bengali text cleaning"]
    end

    subgraph Output["Output"]
        DB2["PostgreSQL: gov_bd_pages\nstatus='success'/failed/error\n- url, title, markdown_body"]
    end

    Text --> Loader
    Loader --> DB1
    DB1 --> Crawler
    Crawler --> DB2
```

│ └─────────┴─────────┴───────────┘│
└──────────────────────────────────┘
```

---

## Usage Examples

### Full Pipeline

```bash
python main.py
```

### After First Run (Skip URL Loading)

Comment out line 150 in `crawler.py`:
```python
# load_urls_from_txt(txt_file)  # Commented after first run
```

### Manual URL Insertion

```python
from database import insert_pending_url
insert_pending_url("https://example.gov.bd")
```

### Check Pending URLs

```python
from database import get_pending_urls
pending = get_pending_urls()
print(f"{len(pending)} URLs to crawl")
```

---

## Troubleshooting

### "No pending URLs to crawl"

- URLs already processed (check status != 'pending')
- Need to run `load_urls_from_txt()` first

### Connection Error

- Ensure PostgreSQL is running: `docker-compose up -d`
- Check credentials in `config.py`

### Slow Crawling

- Increase/politeness delay in `process_pending_urls()`
- Check network connectivity

### Empty Markdown

- URL may have JavaScript-heavy content
- Crawler may not extract dynamic content

---

*Last Updated: April 2026*
