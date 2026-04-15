# Code Documentation - IPO (Input-Process-Output)

This directory contains IPO documentation for each component of the Website Discovery Service.

## IPO Documentation

### Input-Process-Output Format

Each component is documented with:
- **Input**: What data/parameters the component receives
- **Process**: How the component processes the input
- **Output**: What data/results the component produces
- **Usage**: Where and how to use the component

---

## Configuration (`src/config/`)

### `src/config/settings.py` - Configuration Settings

| Aspect | Details |
|--------|---------|
| **Input** | Environment variables (.env), config.yaml defaults |
| **Process** | Pydantic v2 models validate and merge settings |
| **Output** | Singleton `settings` object with type-safe access |
| **Usage** | `from src.config.settings import settings` |

**Sub-settings:**
- `settings.database` - PostgreSQL connection settings
- `settings.crawler` - Discovery engine parameters
- `settings.scheduler` - Queue scheduling settings
- `settings.liveness` - Status check configuration
- `settings.logging` - Loguru setup
- `settings.metrics` - Metrics collection config

---

## Database (`src/database/`)

### `src/database/models.py` - Pydantic ORM Models

| Aspect | Details |
|--------|---------|
| **Input** | Database row data (dict/Record) |
| **Process** | Pydantic validation and model instantiation |
| **Output** | Type-safe Domain, SeedUrl, UrlQueue, DiscoveryLog objects |
| **Usage** | `Domain.from_row(row)` or `Domain(domain="example.gov.bd")` |

**Models:**
- `Domain` - Discovered domain tracking
- `SeedUrl` - Seed URL management
- `UrlQueue` - Processing queue
- `DiscoveryLog` - Audit trail
- `DiscoveryStats` - Aggregated statistics

### `src/database/connection.py` - Connection Pooling

| Aspect | Details |
|--------|---------|
| **Input** | Database credentials from settings |
| **Process** | asyncpg connection pool management |
| **Output** | Connection pool and acquire contexts |
| **Usage** | `pool = await get_pool()`, `async with pool.acquire() as conn:` |

### `src/database/schema.py` - Schema Initialization

| Aspect | Details |
|--------|---------|
| **Input** | SQL migration file |
| **Process** | Execute schema SQL (tables, indexes, views, triggers) |
| **Output** | Initialized database structure |
| **Usage** | `await initialize_schema()` |

---

## Crawler (`src/crawler/`)

### `src/crawler/engine.py` - Discovery Engine

| Aspect | Details |
|--------|---------|
| **Input** | Seed URLs from database, configuration |
| **Process** | Queue processing, concurrent HTTP requests, domain extraction |
| **Output** | Discovered domains saved to database |
| **Usage** | `engine = DiscoveryEngine()`, `await engine.run()` |

**Key methods:**
- `run()` - Main discovery loop
- `_load_seed_urls()` - Load seeds from database
- `_process_url()` - Process single URL
- `_save_domain()` - Save to database

### `src/crawler/finder.py` - Domain Finder

| Aspect | Details |
|--------|---------|
| **Input** | URL string, HTML content |
| **Process** | HTTP fetch, HTML parsing, domain extraction, filtering |
| **Output** | List of Domain objects for .gov.bd domains |
| **Usage** | `finder = DomainFinder()`, `await finder.find_domains_from_url(url, session)` |

**Key methods:**
- `normalize_domain()` - Clean domain name
- `is_allowed_domain()` - Check .gov.bd TLD
- `extract_links_from_html()` - Parse HTML for links

### `src/crawler/queue.py` - Priority Queue

| Aspect | Details |
|--------|---------|
| **Input** | URL string, priority level (1-5) |
| **Process** | Priority-based ordering, deduplication |
| **Output** | UrlQueue items ordered by priority |
| **Usage** | `queue.add(url, priority=1)`, `await queue.get_next()` |

**Priority levels:**
- 1: Critical (seed URLs)
- 2: High (rediscovered)
- 3: Medium (regular discovery)
- 4: Low (liveness checks)

---

## Services (`src/services/`)

### `src/services/liveness.py` - Liveness Service

| Aspect | Details |
|--------|---------|
| **Input** | Domain name |
| **Process** | HTTP request, status code check, response time measurement |
| **Output** | LivenessCheckResult with is_live status |
| **Usage** | `service = LivenessService()`, `await service.check_domain(domain)` |

**Key methods:**
- `check_domain()` - Single domain check
- `check_batch()` - Parallel domain checks
- `update_database()` - Save results to database

### `src/services/health.py` - Health Service

| Aspect | Details |
|--------|---------|
| **Input** | None (checks system internally) |
| **Process** | Database ping, disk space check, memory check |
| **Output** | Health status dictionary |
| **Usage** | `service = HealthService()`, `await service.check()` |

**Checks:**
- Database connectivity
- Disk space
- Memory usage
- Service status

### `src/services/metrics.py` - Metrics Service

| Aspect | Details |
|--------|---------|
| **Input** | Metric names, values |
| **Process** | Counter/gauge updates, histogram recording |
| **Output** | Formatted metrics (Prometheus/JSON) |
| **Usage** | `service.increment("discoveries")`, `service.get_metrics()` |

**Metric types:**
- Counters - Discoveries, checks, errors
- Gauges - Queue depth, discovered count
- Histograms - Response times

---

## Tools (`src/tools/`)

### `src/tools/ingest_seed_urls.py` - Seed URL Ingestion

| Aspect | Details |
|--------|---------|
| **Input** | .txt file with URLs (one per line), source type |
| **Process** | Parse file, validate URLs, upsert to database |
| **Output** | Statistics (inserted, skipped, errors) |
| **Usage** | `python -m src.tools.ingest_seed_urls seeds.txt manual` |

**Command line:**
```bash
python -m src.tools.ingest_seed_urls <file.txt> [source]
Sources: manual, batch, api, import, export
```

### `src/tools/status_report.py` - Status Report

| Aspect | Details |
|--------|---------|
| **Input** | Database connection |
| **Process** | Query tables/views, aggregate statistics |
| **Output** | Formatted status report (text/JSON) |
| **Usage** | `python -m src.tools.status_report` |

**Command line:**
```bash
python -m src.tools.status_report [--format json] [--output file.txt]
```

---

## Entry Point (`main.py`)

### `src/main.py` - Service Entry Point

| Aspect | Details |
|--------|---------|
| **Input** | Configuration from settings, signal events |
| **Process** | Initialize database, start discovery loop, handle shutdown |
| **Output** | Continuous discovery service |
| **Usage** | `python -m src.main` |

**Lifecycle:**
1. Setup logging
2. Initialize database
3. Start discovery engine
4. Process continuous loop
5. Handle signals (Ctrl+C)
6. Graceful shutdown

---

## Scripts

### `scripts/setup_database.py` - Database Setup

| Aspect | Details |
|--------|---------|
| **Input** | Database credentials from .env |
| **Process** | Create database/user, run migrations, grant permissions |
| **Output** | Initialized database with schema |
| **Usage** | `python scripts/setup_database.py` |

**Steps:**
1. Connect to PostgreSQL
2. Create user if needed
3. Create database if needed
4. Grant permissions
5. Run schema migration
6. Verify setup

---

## Testing

### `tests/unit/` - Unit Tests

| File | Tests |
|------|-------|
| `test_config.py` | Configuration validation, environment overrides |
| `test_database_models.py` | Model validation, from_row conversion |
| `test_crawler.py` | Domain extraction, queue operations |

### `tests/integration/` - Integration Tests

| File | Tests |
|------|-------|
| `test_end_to_end.py` | Database operations, service lifecycle |

---

## See Also

- [Main README](../README.md) - Project overview
- [Architecture](../architecture.md) - System design
- [Database Schema](../db_diagram.md) - Database documentation
- [Optimization Guide](../optimization.md) - Performance tuning
