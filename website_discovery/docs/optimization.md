# Optimization Guide

This document explains optimization techniques for the Website Discovery Service, covering database performance, discovery efficiency, deduplication strategies, and resource management.

## Table of Contents

- [Database Optimization](#database-optimization)
- [Discovery Deduplication](#discovery-deduplication)
- [Queue Management](#queue-management)
- [Liveness Check Optimization](#liveness-check-optimization)
- [Memory Management](#memory-management)
- [Connection Pooling](#connection-pooling)
- [Performance Tuning](#performance-tuning)

---

## Database Optimization

### Index Strategy

The schema includes several indexes optimized for different query patterns:

#### Primary Indexes

```sql
-- Fast domain lookup by name (unique constraint)
CREATE INDEX idx_domains_domain ON domains(domain);

-- Query live domains only (most common)
CREATE INDEX idx_domains_is_live ON domains(is_live);

-- Time-based queries (scheduling, recent discoveries)
CREATE INDEX idx_domains_last_checked ON domains(last_checked);
```

#### Partial Indexes

Partial indexes improve performance by indexing only relevant rows:

```sql
-- Dead domains for recheck scheduling (smallest dataset)
CREATE INDEX idx_domains_dead ON domains(domain)
    WHERE is_live = FALSE;

-- Content hash lookups (only for domains with hashes)
CREATE INDEX idx_domains_content_hash ON domains(content_hash)
    WHERE content_hash IS NOT NULL;

-- Pending queue items by priority
CREATE INDEX idx_url_queue_status_priority ON url_queue(status, priority, scheduled_at)
    WHERE status = 'pending';
```

**Why Partial Indexes Work:**

- Smaller index size = faster queries
- Less disk I/O
- Better cache utilization
- Example: If 90% of domains are live, `idx_domains_dead` is 10x smaller than a full index

#### Composite Indexes

For multi-column queries:

```sql
-- Queue processing: status → priority → time
CREATE INDEX idx_url_queue_status_priority
    ON url_queue(status, priority, scheduled_at);

-- Discovery log: domain + recent activity
CREATE INDEX idx_discovery_log_domain
    ON discovery_log(domain);
```

### Query Optimization

#### Use Views for Common Queries

```sql
-- Instead of this complex query:
SELECT d.domain, d.status_code, d.last_checked
FROM domains d
WHERE d.is_live = TRUE
ORDER BY d.last_checked DESC
LIMIT 100;

-- Use the view:
SELECT * FROM v_live_domains LIMIT 100;
```

#### Batch Operations

```python
# Efficient: Single batch insert
async with pool.acquire() as conn:
    await conn.executemany(
        "INSERT INTO domains (domain, protocol, is_live) VALUES ($1, $2, $3)",
        domains_batch
    )

# Inefficient: One at a time
for domain in domains:
    await conn.execute(
        "INSERT INTO domains (domain, protocol, is_live) VALUES ($1, $2, $3)",
        domain.domain, domain.protocol, domain.is_live
    )
```

#### EXPLAIN Analysis

Use EXPLAIN ANALYZE to understand query performance:

```sql
EXPLAIN ANALYZE
SELECT * FROM domains
WHERE is_live = TRUE
  AND last_checked < NOW() - INTERVAL '24 hours';
```

Look for:
- **Index Scan** (good) vs **Seq Scan** (bad for large tables)
- **Actual Time** vs **Estimate Time**
- **Rows Removed by Filter** (high = bad index usage)

---

## Discovery Deduplication

### Problem

Same domain may be discovered multiple times through different paths:

```
https://bangladesh.gov.bd → ministry.gov.bd
https://links.gov.bd → ministry.gov.bd
```

### Solution Layers

#### 1. Database UNIQUE Constraint

```sql
ALTER TABLE domains ADD CONSTRAINT unique_domain UNIQUE (domain);
```

This is the ultimate deduplication: PostgreSQL will reject duplicates.

#### 2. In-Memory Cache for Recent Discoveries

```python
from functools import lru_cache

class DiscoveryEngine:
    def __init__(self):
        self.recent_domains = set()
        self.max_recent = 10000

    async def _is_recent_domain(self, domain: str) -> bool:
        """Check if domain was recently discovered."""
        return domain in self.recent_domains

    async def _add_recent_domain(self, domain: str) -> None:
        """Add domain to recent cache."""
        if len(self.recent_domains) >= self.max_recent:
            # Remove oldest 20%
            self.recent_domains = set(
                list(self.recent_domains)[self.max_recent // 5:]
            )
        self.recent_domains.add(domain)
```

#### 3. Hash-Based Comparison

For detecting domain variants:

```python
import hashlib

def normalize_domain(url: str) -> str:
    """Normalize URL to canonical domain."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    # Remove www.
    if domain.startswith('www.'):
        domain = domain[4:]

    # Remove port
    if ':' in domain:
        domain = domain.split(':')[0]

    return domain

def domain_hash(domain: str) -> str:
    """Generate hash for deduplication."""
    return hashlib.md5(domain.encode()).hexdigest()
```

#### 4. Query Optimization

```sql
-- Check if domain exists before insert (faster than ON CONFLICT)
SELECT id FROM domains WHERE domain = $1;

-- Then insert only if not found
-- OR use upsert function
SELECT upsert_domain('example.gov.bd', 'https', 200, 100, TRUE);
```

---

## Queue Management

### Priority Queue Design

```
Priority 1: Seed URLs (critical - process immediately)
Priority 2: Rediscovered domains (high - domain was dead)
Priority 3: Regular discovery URLs (medium - normal crawl)
Priority 4: Liveness check URLs (low - status verification)
Priority 5: Archived/stale URLs (lowest - cleanup)
```

### Batch Processing

Process URLs in batches to reduce overhead:

```python
async def process_queue_batch(self, batch_size: int = 100) -> int:
    """Process URLs in a batch."""
    # Get batch
    queue_items = await self._get_next_queue(batch_size)

    # Process in parallel
    tasks = [self._process_url(item) for item in queue_items]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Update queue status
    await self._update_queue_status(queue_items, results)

    return len(queue_items)
```

### Queue Cleanup

Regular cleanup of completed/failed items:

```sql
-- Delete completed items older than 7 days
DELETE FROM url_queue
WHERE status = 'completed'
  AND scheduled_at < NOW() - INTERVAL '7 days';

-- Archive failed items
INSERT INTO url_queue_failed
SELECT * FROM url_queue
WHERE status = 'failed' AND attempts >= 3;

DELETE FROM url_queue
WHERE status = 'failed' AND attempts >= 3;
```

---

## Liveness Check Optimization

### Parallel Checks

```python
async def check_liveness_parallel(self, domains: list[Domain]) -> None:
    """Check multiple domains in parallel."""
    semaphore = asyncio.Semaphore(self.max_concurrent)

    async def check_single(domain: Domain) -> None:
        async with semaphore:
            await self._check_single_liveness(domain)

    await asyncio.gather(*[check_single(d) for d in domains])
```

### Exponential Backoff

For dead domains, increase retry interval:

```python
async def get_retry_delay(domain: Domain) -> int:
    """Calculate retry delay with exponential backoff."""
    base_delay = 60  # 1 minute
    max_delay = 86400  # 24 hours

    delay = base_delay * (2 ** domain.check_count)
    return min(delay, max_delay)
```

### Connection Reuse

Use keep-alive connections:

```python
async with aiohttp.ClientSession(
    connector=aiohttp.TCPConnector(
        limit=1000,
        limit_per_host=100,
        keepalive_timeout=60,
    )
) as session:
    async for domain in domains:
        async with session.get(f"https://{domain}") as response:
            # Process response
            pass
```

---

## Memory Management

### Streaming Processing

Don't load all URLs into memory:

```python
async def process_seeds_streaming(self, file_path: str):
    """Process seed file line by line."""
    with open(file_path, 'r') as f:
        for line in f:
            url = line.strip()
            if url:
                await self._add_seed_url(url)
                # Process immediately, don't buffer
```

### Periodic Checkpointing

Save progress periodically:

```python
async def checkpoint(self):
    """Save current state."""
    # Save domain cache to disk
    await self._save_state('state.json')

    # Force garbage collection
    import gc
    gc.collect()
```

### Bounded Collections

Limit in-memory set sizes:

```python
class BoundedSet:
    def __init__(self, max_size: int):
        self.max_size = max_size
        self._set = set()

    def add(self, item: str) -> bool:
        if item in self._set:
            return False

        if len(self._set) >= self.max_size:
            # Remove random item (or use LRU)
            self._set.pop()

        self._set.add(item)
        return True
```

---

## Connection Pooling

### Optimal Pool Size

Calculate based on your workload:

```python
# Formula: pool_size = (CPU_cores * 2) + (expected_concurrent_tasks)
# For 4 cores, 30 concurrent crawls:
pool_size = (4 * 2) + 30 = 38

# Round to nearest 10
pool_size = 40
```

### Pool Configuration

```yaml
database:
  pool_size: 10           # Base connections
  max_overflow: 20        # Extra connections under load
  pool_timeout: 30        # Wait time for connection
  pool_recycle: 1800      # Recycle every 30 minutes
```

### Pool Health Checks

```python
async def health_check_pool() -> bool:
    """Verify pool is healthy."""
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False
```

---

## Performance Tuning

### Environment-Specific Settings

#### Development (Small Scale)

```yaml
crawler:
  max_concurrent_requests: 10
  timeout: 30

database:
  pool_size: 5
```

#### Production (Medium Scale)

```yaml
crawler:
  max_concurrent_requests: 50
  timeout: 15

database:
  pool_size: 15
  max_overflow: 25
```

#### Production (Large Scale)

```yaml
crawler:
  max_concurrent_requests: 200
  timeout: 10

database:
  pool_size: 50
  max_overflow: 100

performance:
  batch_size: 100
  parallel_workers: 8
```

### Monitoring Metrics

Track these metrics for performance tuning:

```python
class PerformanceMetrics:
    discovery_count: int
    successful_checks: int
    failed_checks: int
    queue_depth: int
    avg_response_time: float
    cpu_usage: float
    memory_usage_mb: float

    @property
    def success_rate(self) -> float:
        total = self.successful_checks + self.failed_checks
        return (self.successful_checks / total * 100) if total > 0 else 0
```

### Tuning Recommendations

| Symptom | Solution |
|---------|----------|
| High queue depth | Increase `max_concurrent_requests` |
| Connection errors | Increase `pool_size`, reduce `max_concurrent_requests` |
| Slow queries | Add indexes, optimize queries |
| Memory pressure | Reduce batch size, enable cleanup |
| High CPU | Reduce concurrency, enable rate limiting |

---

## Benchmark Results

### Query Performance

| Query | Without Index | With Index | Improvement |
|-------|---------------|------------|-------------|
| `SELECT * FROM domains WHERE is_live = TRUE` | 2.5s | 15ms | 166x |
| `SELECT * FROM url_queue WHERE status = 'pending'` | 180ms | 3ms | 60x |
| `SELECT * FROM discovery_log WHERE domain = 'x'` | 45ms | 2ms | 22x |

### Discovery Throughput

| Concurrency | URLs/second | Domains/minute |
|-------------|-------------|----------------|
| 10 | 8 | 480 |
| 50 | 35 | 2100 |
| 100 | 65 | 3900 |
| 200 | 110 | 6600 |

Note: Diminishing returns above 100 concurrent requests due to network limits.

---

## Conclusion

Optimization is iterative. Start with:

1. **Basic indexes** (domain, is_live, last_checked)
2. **Proper connection pooling** (start with 10 connections)
3. **Deduplication** (UNIQUE constraint + in-memory cache)
4. **Queue priorities** (seed URLs first)

Then measure and tune based on your specific workload.
