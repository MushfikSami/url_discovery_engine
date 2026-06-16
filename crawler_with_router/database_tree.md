# gov_spider_db — Database Tree Diagram

*Generated: 2026-05-04 | Total DB size: ~18 GB | Total rows: ~4.8M*

## Entity Relationship Tree

```
┌─────────────────────────────────────────────────────────────────────────┐
│ seed_websites (39,752 rows | 11 MB)                                      │
│ ─────────────────────────────────────────────────────────────────────── │
│ PK  website_url    TEXT        "https://hatia.noakhali.gov.bd"           │
│     status         VARCHAR(20) 'pending' | 'processing' | 'completed'   │
│ ─────────────────────────────────────────────────────────────────────── │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ Contains →                                                        │   │
│  │   39,750 unique base domains (0.05% orphaned)                    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                     │                                                    │
│                     │ 1:N                                                │
│                     ▼                                                    │
│ ┌─────────────────────────────────────────────────────────────────┐      │
│ │ spider_queue (2,774,723 rows | 4,729 MB ≈ 4.6 GB)              │      │
│ │ ────────────────────────────────────────────────────────────── │      │
│ │ PK  url            TEXT        "https://hatia.noakhali.gov.bd/..."│      │
│ │     base_domain    TEXT        "https://hatia.noakhali.gov.bd"   │      │
│ │     status         VARCHAR(20) 'pending' | 'processing'         │      │
│ │     added_at       TIMESTAMP    creation time                    │      │
│ │ ────────────────────────────────────────────────────────────── │      │
│ │ Indexes: base_domain + status  (2,577 MB)                        │      │
│ │ Status breakdown:                                              │      │
│ │   completed:  2,774,374   (99.9985%)                           │      │
│ │   failed:         345     (0.0015%) — dead links / timeouts    │      │
│ │   pending:          0     (0.0%)                                │      │
│ │ ────────────────────────────────────────────────────────────── │      │
│ │  ┌──────────────────────────────────────────────────────┐      │      │
│ │  │ Extracted →                                         │      │      │
│ │  │   474.8 pages/min average crawl speed               │      │      │
│ │  │   avg 71 pages/domain (range: 1–57,592)            │      │      │
│ │  └──────────────────────────────────────────────────────┘      │      │
│ │                     │                                          │      │
│ │                     │ 1:N (same URL key)                       │      │
│ │                     ▼                                          │      │
│ │ ┌─────────────────────────────────────────────────────────┐    │      │
│ │ │ crawled_data (2,025,113 rows | ~13 GB)                 │    │      │
│ │ │ ───────────────────────────────────────────────────── │    │      │
│ │ │ PK  url            TEXT        ← FK matches spider_queue.url │ │      │
│ │ │     raw_markdown   TEXT        avg 11,996 chars (50–499,963)   │ │      │
│ │ │     snippet        TEXT        first 250 chars of markdown    │ │      │
│ │ │     keywords       TEXT[]      top 50 unique words (EN+BN)    │ │      │
│ │ │ ───────────────────────────────────────────────────── │    │      │
│ │ │ Indexes: url (241 MB)                                    │    │      │
│ │ │ Data breakdown:                                        │    │      │
│ │ │   raw_markdown:     9.3 GB total                       │    │      │
│ │ │   snippet:           2.1 GB total                       │    │      │
│ │ │   keywords:          2.1 GB total                       │    │      │
│ │ ───────────────────────────────────────────────────── │    │      │
│ │                     │                                  │    │      │
│ │                     │ 1:1 (via url)                    │    │      │
│ │                     ▼                                  │    │      │
│ │ ┌─────────────────────────────────────────────────────┐│    │      │
│ │ │ domain_hierarchy (39,750 rows | 65 MB)             ││    │      │
│ │ │ ──────────────────────────────────────────────────││    │      │
│ │ │ PK  website      TEXT        same as seed_websites ││    │      │
│ │ │     web_pages    TEXT[]      array of all URLs     ││    │      │
│ │ │                              crawled for this domain││    │      │
│ │ │ ──────────────────────────────────────────────────││    │      │
│ │ │ Indexes: website (3,232 kB)                       ││    │      │
│ │ └─────────────────────────────────────────────────────┘│    │      │
│ └─────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Filter Funnel

```
                    Discovered Links (spider_queue)
                    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2,774,723 rows
                            │
                            │  ↓ Trap Killers (spider.py §0–19)
                            │     Path recursion, CMS loops,
                            │     media extensions, pagination traps,
                            │     encrypted payloads, JS sessions
                            │
                    Crawled URLs (spider_queue.completed)
                    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2,774,374
                            │
                            │  ↓ URL Filters (strategy.md Phase 1)
                            │     CMS routing mutations, UGC,
                            │     legacy DBs, WordPress uploads
                            │
                    Fetched & Parsed (raw)
                    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ~2,807,565
                            │
                            │  ↓ Payload Sanitization (strategy.md Phase 2)
                            │     MD5 dedup (−~800K duplicates),
                            │     Base64 >500K chars deleted,
                            │     empty pages, error pages, SEO spam,
                            │     mojibake, orphan cleanup
                            │
                    crawled_data (clean markdown)
                    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2,025,113 rows  |  ~13 GB
```

## Summary Metrics

| Table | Rows | Total Size | Data | Indexes |
|-------|------|-----------|------|---------|
| `seed_websites` | 39,752 | 11 MB | 6.5 MB | 4.2 MB |
| `spider_queue` | 2,774,723 | 4,729 MB (4.6 GB) | 2,266 MB | 2,577 MB |
| `domain_hierarchy` | 39,750 | 65 MB | 29 MB | 3.2 MB |
| `crawled_data` | 2,025,113 | ~13 GB | 2.2 GB | 241 MB |
| **Total** | **~4.8M** | **~18 GB** | **4.5 GB** | **2.8 GB** |
