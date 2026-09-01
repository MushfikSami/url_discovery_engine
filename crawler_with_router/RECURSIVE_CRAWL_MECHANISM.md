# Recursive Web-Crawl Mechanism — A Reusable Design

A design pattern for **discovering and crawling every internal page of a website
starting from a single seed**, using a work-queue instead of call-stack
recursion. It is site-agnostic and **storage-agnostic**: the reference
description below uses an **in-memory frontier backed by a temporary log file**
that is deleted once the crawl completes (no database required); an optional
database backend is described in §12 for the multi-process case.

Everything is generic — concrete names (functions, files) are yours to choose.

---

## 1. Core idea: recursion as a work-queue (BFS)

The crawl is **recursive in effect, iterative in implementation**. Nothing calls
itself. Instead, recursion is expressed as a **breadth-first traversal driven by
a frontier queue**:

> Every page crawled yields new links. Those links are pushed back into the same
> queue the crawler is draining. Draining the queue keeps uncovering deeper pages
> until nothing new appears. **The queue is the recursion stack.**

The frontier lives in memory for speed; a small **append-only temp file mirrors
it** so an interrupted crawl can resume, and the file is **deleted on clean
completion**. A **visited-set** (also in memory, mirrored to the same file)
guarantees each URL is processed once (§5).

```
seed ─▶ [fetch page] ─▶ [extract links] ─▶ [filter] ─▶ [enqueue NEW links]
            ▲                                                    │
            └──────────────── pop next pending page ◀────────────┘
                           (loops until frontier empty)
```

---

## 2. State model (three in-memory collections + one temp file)

The pattern needs three logical collections. In the fileless/DB-less reference
design they are plain in-memory structures, made crash-resumable by a single
temporary log:

| Collection | Concrete form | Purpose |
|-----------|---------------|---------|
| **Seed list** | a list/iterable of target roots | Top-level sites to crawl. |
| **Frontier** | a FIFO queue (`collections.deque` / `asyncio.Queue`) | Pages awaiting crawl — the live recursion stack. FIFO order gives BFS. |
| **Visited-set** | a `set` of normalized URLs | Every URL ever enqueued — prevents re-crawling and loops. |
| **Content sink** | files on disk, an object store, an API, etc. | Where parsed page content goes. |

### The temporary log file
A single append-only text file (e.g. `crawl_state.log`) is the **only**
persistence. Each time a URL is enqueued, append one line:

```
<status>\t<url>            e.g.   PENDING   https://site/notice/12
                                  DONE      https://site/notice/12
```

- **On start:** if the file exists, replay it to rebuild the visited-set and
  re-enqueue every URL not marked `DONE` → **resume** exactly where it stopped.
- **During the crawl:** append `PENDING` when a URL is first enqueued, append
  `DONE` when a page finishes. (Appends are cheap and crash-safe; the file is a
  journal, not a rewrite target.)
- **On clean completion:** the crawl is finished, so the journal is disposable —
  **delete the temp file.** A fresh run then starts clean.

> The visited-set is the deduplication mechanism; the log file is just its
> durable shadow for resume. If you don't need resume, you can drop the file
> entirely and keep everything in memory.

---

## 3. The two-level loop

### Outer loop — one target at a time
1. Take the next `pending` seed. Processing one target fully before the next
   keeps each crawl self-contained and makes failure recovery trivial.
2. **Seed the frontier** with that target's root URL (enqueue + mark visited).

### Inner loop — drain that target's frontier (the recursion)
Repeat until the frontier is empty:
1. **Pop** the oldest pending page (FIFO → **breadth-first**: shallower pages
   before the deeper ones they spawned).
2. **Process** the page: fetch → discover links → parse → save (§4–§7).
3. **Enqueue** newly discovered links — *this is the recursive step.*
4. Journal the page as `DONE`.
5. When the frontier is empty, the target is finished; move to the next seed.

```text
for each SEED:
    enqueue(seed_root); mark_visited(seed_root)
    while frontier not empty:
        page   = frontier.popleft()          # BFS order
        links  = process(page, target=seed)  # §4
        for link in links:                   # §5  ← recursion
            if link not in visited:
                visited.add(link); journal("PENDING", link)
                frontier.append(link)
        journal("DONE", page)
    # target done
delete_temp_file()                            # §2, on clean completion
```

---

## 4. Per-page processing: fetch → discover → route → save

### 4a. Fetch
An async HTTP GET with a **hard timeout**, **redirect-following**, and tolerant
TLS. On any network error, return "no links / nothing saved" so one bad page
never stalls the crawl.

### 4b. Discover candidate links
Parse the HTML, then for every anchor turn its `href` into an **absolute,
normalized** URL:

```python
full_url = urljoin(current_page_url, href).split('#')[0]
```

- `urljoin` resolves relative links against the current page.
- **Strip the fragment** (`#…`) so `page#a` and `page#b` collapse to one URL —
  this alone removes a large class of duplicates.

Collect only URLs passing **both** gates below into a per-page `set`:

```python
if full_url.startswith(target_root) and not is_binary(full_url):
    candidates.add(full_url)
```

`is_binary` skips document/archive extensions (`.pdf`, `.zip`, `.doc`, `.xlsx`, …)
you don't want to treat as crawlable HTML.

---

## 5. Deduplication & the visited-set (why it can't loop forever)

Three layers guarantee each page is enqueued and crawled **once**:

1. **In-page dedup** — collect links into a `set`.
2. **Global dedup** — check membership against the visited-set before enqueueing;
   add on first sight:

   ```python
   if link not in visited:
       visited.add(link)
       frontier.append(link)
       journal("PENDING", link)
   ```

3. **Resume dedup** — on restart, the visited-set is rebuilt from the temp file,
   so a resumed crawl never re-enqueues URLs it already saw.

A page linked from 500 others is enqueued once. This is the textbook
*frontier + visited-set* BFS; the `set` is the visited-set and the temp file is
its durable shadow.

---

## 6. Bounding the recursion: scope + trap filtering

Two constraints keep the traversal finite and on-target.

### 6a. Same-site boundary
Confine discovery to the current target by requiring `url.startswith(target_root)`
(root = `scheme://host`). External links are seen but never enqueued — no
cross-site sprawl, and each target's crawl stays self-contained.

### 6b. Trap filtering (pre-download)
Real sites (especially CMS-driven ones) generate **infinite or worthless URL
spaces**: calendars, faceted search, session-tagged links, pagination to page
23,000, user profiles, media galleries, print/lang variants. If these entered
the frontier, BFS would never terminate. **Filter them out *before* download**
with a tunable rule set. Generic categories worth blocking:

| Category | Pattern signal |
|----------|----------------|
| Malformed / oversized | stray `<>{}[]`, spaces, URL length over a cap (e.g. 250) |
| **Repeating path segments** (routing loops) | any path segment appearing more than N times (`/home/home/home/`) |
| Session / auth / encoded params | `;jsessionid=`, `session=`, `response_type=code`, opaque base64 blobs, trailing `==` |
| Faceted / infinite search | `/search?`, `search/all/`, `…&page=<huge>` |
| Media & uploads | `/photo`, `/gallery`, `/video`, image extensions, upload dirs |
| CMS routing internals | framework-specific route prefixes (`/node/`, `/views/`, …) |
| Legacy DB detail explosions | per-record detail routes that fan out combinatorially |
| User-generated content | profiles, submissions, per-user report pages |
| Print / language duplicates | `-print-`, `?lang=`, tracking query params |

Keep these rules in **one place** as config. Net effect: the frontier only grows
with **real, unique, content-bearing pages**, so the BFS provably drains.

---

## 7. Parser routing: turning a page into content

Discovery and content-extraction are separate concerns. Route each page by type:

```
looks JavaScript-heavy (SPA)?
    ├─ yes ─▶ render in a headless browser, then extract   (slow, heavy)
    └─ no  ─▶ strip + convert static HTML directly          (fast, cheap)
```

- **SPA heuristic**: little visible text but many `<script>` tags, or an empty
  app-root container (`#root` / `#app` / `#__next`). Only these pay the browser cost.
- **Headless-browser path**: run **resource-capped** (headless, disabled GPU,
  media/iframes excluded, a JS-memory cap, and a **short page timeout** to defeat
  bot-wall/redirect loops). Gate it behind a **concurrency semaphore** so browser
  instances can't exhaust RAM.
- **Static path**: cheaply strip `<script>/<style>/<svg>/<img>` and convert to
  markdown/text.

### Validate before saving
Discard the *content* (but still keep the *links* for the frontier) when the page
is a **bot wall** ("just a moment", "enable javascript and cookies", CDN
challenge text) or is **too thin** (below a minimum length). Otherwise save the
content keyed by URL.

> **Key decoupling:** a page can fail the content check yet still contribute its
> outbound links. That is why bot-walled or empty pages don't sever the crawl.

---

## 8. Concurrency model (no database, single process)

With an in-memory frontier the concurrency story is simple and **needs no
row-locking or cross-process coordination**:

- Run **one process** with an `asyncio` event loop and a pool of N worker
  coroutines sharing **one** `asyncio.Queue` (frontier) and one `set` (visited).
- Under `asyncio`, a single `queue.get()` / `visited` check-and-add runs to
  completion without preemption on the event loop, so **no explicit locks are
  needed** for the queue and set. (If you ever move to real threads, guard the
  `set` and the file append with a single `threading.Lock`.)
- The **only** concurrency limiter you actively need is the **browser semaphore**
  from §7, bounding how many headless renders run at once (RAM control).
- Workers loop: `pop → process → enqueue new → journal DONE`, and idle-wait when
  the queue is momentarily empty but other workers are still in flight.

```text
async def worker(frontier, visited, sem):
    while not done():
        page = await frontier.get()
        links = await process(page)          # uses `sem` only for browser path
        for link in links:
            if link not in visited:
                visited.add(link); journal("PENDING", link); frontier.put_nowait(link)
        journal("DONE", page); frontier.task_done()
```

Termination is coordinated by the queue itself (e.g. `await frontier.join()`)
rather than by polling a database — see §10.

---

## 9. Interruption & resume (the temp file's real job)

Because the frontier is in memory, a crash would normally lose all progress. The
temp log prevents that:

- Every enqueue and completion is appended to the log **as it happens**.
- On restart, replay the log: URLs marked `DONE` go straight into the visited-set
  (never re-crawled); URLs seen only as `PENDING` are re-queued. The crawl picks
  up mid-target.
- On **clean completion**, delete the log — its only purpose was resume.

This gives DB-like durability for the frontier with nothing but an append-only
file, and leaves no residue behind after a successful run.

---

## 10. Termination

The crawl stops when **every seed is processed and the frontier is empty**:

```
no seed left to start   AND   frontier is empty (all workers idle)   ⟶   done
                                                            │
                                                            ▼
                                                delete temp log file
```

With `asyncio.Queue`, `await frontier.join()` blocks until every enqueued item
has a matching `task_done()`, which is the natural "frontier drained" signal.
Because every step enqueues strictly *new* URLs (§5) and scope + trap filters
bound the URL space (§6), the frontier is guaranteed to shrink to empty.

---

## 11. End-to-end summary

```
        ┌──────────────────────────────────────────────────────────────┐
        │  SEED LIST (target roots)                                     │
        └───────────────┬──────────────────────────────────────────────┘
        take next seed   │
                         ▼
          seed root URL ──▶ FRONTIER (in-memory FIFO)  +  temp log "PENDING"
                         │
   ┌──────────────────────┼──────────────────────────────────────────────┐
   │ INNER LOOP (BFS)      ▼                                              │
   │        pop oldest page (FIFO)                                        │
   │                      │                                             │
   │      HTTP GET ──▶ parse HTML ──▶ extract <a href>                  │
   │                      │                                             │
   │  urljoin + strip #  ──▶ trap filters ──▶ same-site gate           │
   │                      │                                             │
   │  new link & not in visited? ──▶ visited.add + enqueue + log ──────┤ recurse
   │                      │                                             │
   │  SPA? ──yes──▶ headless-browser render (semaphore-gated)          │
   │       └──no──▶ static HTML→markdown                                │
   │                      │                                             │
   │  content valid? ──▶ save to content sink                          │
   │                      │                                             │
   │  log page "DONE" ────┘   (loop until frontier empty)              │
   └────────────────────────────────────────────────────────────────────┘
                         │
              next seed … then, when all done ──▶ delete temp log file
```

**In one sentence:** seed a target's root, then repeatedly pop the oldest
unvisited page from an in-memory frontier, extract and filter its in-scope links,
push the genuinely new ones back into that same frontier (dedup enforced by a
visited-set mirrored to a temp log for resume), and render each page to content —
looping breadth-first until the frontier for every target is empty, then delete
the temp log.

---

## 12. Optional: swapping the backend for multiple processes

The in-memory + temp-file model assumes **one process**. If you later need
**many independent processes/machines** sharing one frontier, swap the queue for
a store that supports an **atomic claim** so no two workers take the same URL:

- **Database:** a `frontier` table with a UNIQUE `url` and
  `INSERT … ON CONFLICT DO NOTHING` for dedup; claim the next page with
  `UPDATE … WHERE url = (SELECT … WHERE status='pending' ORDER BY discovered_at
  LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING url`. `SKIP LOCKED` is what prevents
  double-crawling across workers.
- **Redis / queue service:** an atomic `BRPOPLPUSH` (or a visibility-timeout
  queue) for the frontier, plus a `SET`/Bloom filter for the visited-set.

Everything else in this document — BFS ordering, URL normalization, dedup logic,
scope + trap filters, parser routing, content validation, termination — is
**unchanged**. Only the frontier/visited storage and the claim primitive differ.

---

## 13. Portability checklist

To reuse this design, provide:

- [ ] A **frontier** (FIFO) + a **visited-set**, mirrored to a **temp log** for
      resume, deleted on completion (§2, §9). *(Or a shared atomic-claim store for
      multi-process — §12.)*
- [ ] A **seed list** and the **two-level loop** control flow (§3).
- [ ] URL **normalization** (`urljoin` + fragment strip) and per-page `set` dedup (§4–§5).
- [ ] A **scope rule** (same-site test) and a **trap-filter rule set** as config (§6).
- [ ] A **fetch layer** with timeouts + redirects (§4).
- [ ] A **parser router**: static fast-path + optional headless-browser path,
      resource-capped and concurrency-gated (§7).
- [ ] A **content validator** (bot-wall / min-length) that still returns links (§7).
- [ ] A **termination** signal (frontier drained) that triggers temp-file deletion (§10).
```
