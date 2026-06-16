# v4 Retrieval Speed Test - System Workflow

## Overview

A benchmarking tool that ingests government service data (in Bengali) from a CSV into Elasticsearch, then measures retrieval latency for a sample Bengali search query. It tests how fast a Native Bengali Analyzer can match search queries against indexed government service documents.

## Files

| File | Purpose |
|------|---------|
| [config.py](url_discovery_engine/v4_retrieval_speed_test/config.py) | Central configuration: dataset path, ES host, index name, test query |
| [database.py](url_discovery_engine/v4_retrieval_speed_test/database.py) | Elasticsearch client connection and health check |
| [indexer.py](url_discovery_engine/v4_retrieval_speed_test/indexer.py) | Index creation with Bengali analyzer + bulk CSV ingestion |
| [search.py](url_discovery_engine/v4_retrieval_speed_test/search.py) | Search execution with latency measurement |
| [main.py](url_discovery_engine/v4_retrieval_speed_test/main.py) | Orchestrator: connects, ingests (or skips if cached), searches, displays results |
| [v4_data.csv](url_discovery_engine/v4_retrieval_speed_test/v4_data.csv) | Source dataset (~4.6MB, 8 columns, Bengali government service data) |

## Data Schema (v4_data.csv)

8 columns of Bengali government service data:

| Column | Description |
|--------|-------------|
| Category | Service category (e.g., "স্মার্ট কার্ড ও জাতীয়পরিচয়পত্র") |
| Sub-Category | Sub-category within the category |
| Service | Service name |
| Alternate Variants | Synonyms/aliases (Bengali + English) for SEO |
| Keyword | Target keyword |
| Passage ID | Numeric passage identifier |
| Topic | Question/topic title (Bengali) |
| Text | Full instructional passage in Bengali |
| Text Keywords | Keywords for the passage |
| URL | Source URL |

## Workflow

### Phase 1: Ingestion

```
main.py → get_es_client() → setup_bengali_index() → bulk_ingest_csv()
```

**1. Connect** (`database.py`):
   - Creates `Elasticsearch` client pointing at `http://localhost:9200`
   - Pings to verify connectivity; errors out if unreachable

**2. Create Index** (`indexer.py:setup_bengali_index`):
   - Deletes existing `gov_bengali_data` index if present
   - Creates fresh index with custom mapping:
     - `text_content` → `text` type with `bengali` analyzer (for search)
     - `original_row_id` → `keyword` type (for exact-match filtering)
     - `raw_data` → `object` type with `enabled: false` (stores full CSV row as-is, ES ignores mixed-type issues)

**3. Bulk Ingest** (`indexer.py:bulk_ingest_csv`):
   - Fills all NaN/null values with empty strings
   - For each row, generates a bulk action document:
     - `text_content`: concatenates all non-empty cell values into one space-separated Bengali string (this is what gets searched)
     - `original_row_id`: row index as string
     - `raw_data`: full row as a dict (preserved for display)
   - Uses `helpers.bulk()` for efficient bulk indexing
   - Refreshes the index immediately so documents are searchable
   - Reports count and build time

### Phase 2: Retrieval

```
main.py → execute_search() → ES query → latency measurement → display
```

**1. Search** (`search.py:execute_search`):
   - Runs a `match` query on `text_content` field against the test query: `"আমার বয়স ১২ বছর। আমি কি বয়স্ক ভাতা পেতে পারি?"`
   - Fetches top 3 results by default (configurable via `top_k` parameter)
   - **Starts timer** before query, **stops timer** after response
   - Reports retrieval latency in milliseconds

**2. Display** (`main.py:display`):
   - For each hit, prints:
     - Rank number
     - Relevance score (ES `_score`)
     - All non-empty columns from `raw_data` with their values

## Execution Modes

```
python main.py          # Normal run: reuse existing index if documents exist
python main.py --reset  # Full reset: delete index, re-ingest from CSV
```

The `--reset` flag forces a clean ingest. Without it, the tool checks if the index exists and has documents — if so, it skips ingestion entirely (only runs the search phase).

## Elasticsearch Configuration

- **Host**: `http://localhost:9200` (expects Docker container or local ES instance)
- **Index**: `gov_bengali_data`
- **Analyzer**: `bengali` (Native Bengali Analyzer — handles Bengali script tokenization and stemming)
