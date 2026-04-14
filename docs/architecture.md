# System Architecture

## High-Level Overview

The URL Discovery Engine is a multi-stage pipeline that discovers Bangladesh government websites, extracts and analyzes their content, and provides two distinct AI-powered search systems for answering user queries in formal Bengali.

---

## Data Flow Diagrams

### Overall System Architecture

```mermaid
flowchart TB
    subgraph Stage1["Stage 1: Discovery"]
        Seed["Seed URLs\n- bangladesh.gov.bd\n- ministry lists\n- union lists"]
        Crawler["RecursiveBDCrawler\n- 30 concurrent workers\n- State persistence"]
        Output1["recursive_gov_bd_domains.txt"]
    end

    subgraph Stage2["Stage 2: Liveness Check"]
        DomList["Domain list file"]
        Liveness["live_domains.py\n- 100 concurrent HTTP checks\n- 7-second timeout"]
        Output2["crawled_alive_gov_bd_sites.txt"]
    end

    subgraph Stage3A["Stage 3A: Gov BD Crawler (No LLM)"]
        Loader["loader.py"]
        DB1["database.py"]
        Crawler1["crawler.py\nAsyncWebCrawler"]
        Table1["gov_bd_pages\n- url, title, markdown_body, status"]
    end

    subgraph Stage3B["Stage 3B: Gov BD Crawler (With LLM)"]
        Queue["URL Queue"]
        Crawler2["AsyncWebCrawler\ncrawl4ai"]
        LLM["LLM Processing\nvLLM - Qwen35"]
        Table2["websites\n- url, summary, keywords, raw_markdown"]
        Table3["website_links\n- source_url, target_url"]
    end

    subgraph Stage3C["Stage 3C: Banglapedia Crawler"]
        Gatherer["gatherer.py\nMediaWiki API"]
        DB2["database.py"]
        Crawler3["crawler.py\nContent Cleaner"]
        Table4["banglapedia_pages"]
    end

    subgraph Stage4A["Stage 4A: Tree Index System"]
        Export["db_to_md.py"]
        TreeBuild["tree_index.py\nBM25 Index"]
        Agent["app.py\nReAct Agent Loop"]
        UI["Gradio UI\nlocalhost:7860"]
    end

    subgraph Stage4B["Stage 4B: Elasticsearch System"]
        Setup["setup_es.py"]
        Ingest["ingest_to_es_from_postgres.py"]
        ES["Elasticsearch\nbd_gov_chunks"]
        Query["es_engine.py\nHybrid Search"]
    end

    subgraph Stage5["Stage 5: Evaluation"]
        Queries["queries.csv\n11 test queries"]
        Adapter["eval_adapters.py"]
        Eval["main_eval.py\nDeepEval Metrics"]
        Output3["evaluated_queries.csv"]
    end

    Seed --> Crawler
    Crawler --> Output1
    Output1 --> Liveness
    Liveness --> Output2

    Output2 --> Loader
    Loader --> DB1
    DB1 --> Crawler1
    Crawler1 --> Table1

    Output2 --> Queue
    Queue --> Crawler2
    Crawler2 --> LLM
    LLM --> Table2
    Table2 --> Table3

    Gatherer --> DB2
    DB2 --> Crawler3
    Crawler3 --> Table4

    Table2 --> Export
    Export --> TreeBuild
    TreeBuild --> Agent
    Agent --> UI

    Table2 --> Ingest
    Ingest --> ES
    ES --> Query

    Queries --> Adapter
    Adapter --> Eval
    Eval --> Output3
```

### Crawler Pipeline

```mermaid
sequenceDiagram
    participant User
    participant Crawler
    participant DB as PostgreSQL<br/>(bd_gov_db)
    participant LLM as vLLM Server<br/>(Qwen35)

    User->>Crawler: Start crawler
    Crawler->>DB: Check for pending URLs
    DB-->>Crawler: Return URL list
    loop For each URL
        Crawler->>Crawler: AsyncWebCrawler.arun()
        Crawler->>LLM: Generate summary+keywords
        LLM-->>Crawler: JSON response
        Crawler->>DB: Save to websites table
        Crawler->>DB: Extract links to website_links
    end
    Crawler-->>User: Complete
```

### Tree Index Search Flow

```mermaid
flowchart LR
    subgraph Index["Tree Index"]
        JSON[bd_gov_ecosystem_structure.json]
        Flatten[flatten_tree()]
        BM25[BM25 Index]
    end

    subgraph Search["Search Process"]
        Query[User Query]
        Tokenize[tokenize()]
        Top5[bm25.get_top_n n=5]
        Chunk[chunk_text 2000/300]
        Rerank[chunk_bm25 n=3]
    end

    subgraph Agent["ReAct Agent"]
        Thought[Thought]
        Action[Action: search_tree]
        Obs[Observation]
        Answer[Final Answer]
    end

    JSON --> Flatten --> BM25
    Query --> Tokenize --> Top5
    Top5 --> Chunk
    Chunk --> Rerank
    Rerank --> Obs
    Thought --> Action
    Action --> Obs
    Obs --> Thought
    Obs --> Answer
```

### Elasticsearch Hybrid Search

```mermaid
flowchart LR
    subgraph Setup["Index Setup"]
        ES["Elasticsearch<br/>localhost:9200"]
        Mapping[Index Mapping]
    end

    subgraph Ingest["Data Ingestion"]
        PG[PostgreSQL<br/>websites table]
        Triton[Triton Server<br/>Port 7000]
        Gemma[Gemma Embedding]
        Bulk[Bulk Index]
    end

    subgraph Query["Query Processing"]
        Q["User Query"]
        Embed[Get Embedding]
        KNN[KNN Search<br/>50% weight]
        Multi[Multi-Match<br/>50% weight]
        Result[Ranking]
    end

    Mapping --> ES
    PG --> Triton
    Triton --> Gemma
    Gemma --> Bulk
    Bulk --> ES
    Q --> Embed --> Triton
    Embed --> KNN
    Q --> Multi
    KNN --> Result
    Multi --> Result
    Result --> ES
```

---

---

## Component Details

### 1. Discovery Layer

**Purpose:** Find all .gov.bd domains in Bangladesh.

**Tool:** `bd_recursive_crawler.py`

**Key Features:**
- Asyncio-based with 30 concurrent workers
- State persistence (resumable via `crawler_state.json`)
- Seed URLs from Bangladesh government portal
- Domain extraction and deduplication

**Output:** `recursive_gov_bd_domains.txt`

---

### 2. Liveness Check Layer

**Purpose:** Filter out dead/inactive domains.

**Tool:** `live_domains.py`

**Key Features:**
- 100 concurrent async HTTP requests
- 7-second timeout per domain
- Both HTTP and HTTPS checks
- Status code filtering (<400 = alive)

**Output:** `crawled_alive_gov_bd_sites.txt`

---

### 3. Content Crawling Layer

#### 3A. Gov BD Crawler (Without LLM)

**Purpose:** Basic content extraction without AI enrichment.

**Tool:** `gov_crawler_without_llm/main.py`

**Database:** `gov_bd_pages` table

**Features:**
- Excluded tags filtering
- Bengali text bloat removal
- Status tracking (pending/success/failed/error)

---

#### 3B. Gov BD Crawler (With LLM)

**Purpose:** AI-enriched content with summaries and keywords.

**Tool:** `bd_recursive_crawler.py` (enhanced version)

**Database:** `websites` and `website_links` tables

**LLM Integration:**
- Model: Qwen35 via vLLM
- Prompt: Generate summary + keywords in Bengali
- Output: Strict JSON format
- Context limit: 8000 chars

---

#### 3C. Banglapedia Crawler

**Purpose:** Extract encyclopedia content.

**Tool:** `banglapedia_crawler/main.py`

**Database:** `banglapedia_pages` table

**Features:**
- MediaWiki API for URL gathering
- Article body extraction via CSS selector
- Header/footer bloat removal

---

### 4. Search/Index Layer

#### 4A. Tree Index System

**Purpose:** Hierarchical tree-based search.

**Components:**
- **Index Build:** `db_to_md.py` → Markdown → PageIndex
- **Search Engine:** `tree_index.py` (BM25)
- **Agent:** `agent/app.py` (ReAct loop)

**Data Structure:**
```json
{
  "structure": [
    {
      "node_id": "ministry_of_health",
      "title": "Health Ministry",
      "summary": "...",
      "text": "...",
      "nodes": [...]
    }
  ]
}
```

**Search Process:**
1. User query → Tokenize
2. BM25 top-5 nodes
3. Dynamic chunking (2000 chars, 300 overlap)
4. Re-ranking if >3 chunks
5. Return context to LLM

---

#### 4B. Elasticsearch System

**Purpose:** Hybrid vector+lexical search.

**Components:**
- **Search Engine:** `es_engine.py`
- **Index Setup:** `setup_es.py`
- **Ingestion:** `ingest_to_es_from_postgres.py`

**Index Mapping:**
```json
{
  "chunk_vector": {"type": "dense_vector", "dims": 768},
  "chunk_text": {"type": "text", "analyzer": "bengali"},
  "site_summary": {"type": "text", "analyzer": "bengali"}
}
```

**Search Query:**
```python
{
  "knn": {
    "field": "chunk_vector",
    "query_vector": [...],
    "k": 4,
    "num_candidates": 50,
    "boost": 0.5
  },
  "query": {
    "multi_match": {
      "query": text,
      "fields": ["summary^2", "keywords^1.5", "raw_markdown^1"]
    }
  }
}
```

---

### 5. Evaluation Layer

**Purpose:** Compare Tree Index vs Elasticsearch performance.

**Tool:** `DeepEval/main_eval.py`

**Metrics:**
- Answer Relevancy
- Faithfulness
- Contextual Relevancy

**Judge:** Custom vLLM-based pairwise judge

**Test Queries:** `queries.csv` (11 government-related questions)

---

## Security & Safety

### Guardrails

All agents implement strict safety protocols:

1. **Self-harm/Suicide** - Rejected
2. **Property destruction** - Rejected
3. **Terrorism/Violence** - Rejected
4. **System manipulation** - Rejected

**Guardrail Message (Bengali):**
> "দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"

### Linguisitic Rules

- **Output Language:** Formal Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা)
- **No colloquialisms** or slang
- **Respectful, bureaucratic tone**

---

## Configuration Files

| File | Purpose | Key Settings |
|------|---------|--------------|
| `config.py` (gov) | Gov crawler DB | `dbname: gov_bd_db` |
| `config.py` (banglapedia) | Banglapedia DB | `dbname: banglapedia_db` |
| `agent/config.py` | Tree agent | `MODEL_NAME: qwen35` |
| `elastic_search_engine/config.py` | ES agent | `TRITON_URL: localhost:7000` |
| `docker-compose.yml` | PostgreSQL | `POSTGRES_PASSWORD: password` |

---

*Last Updated: April 2026*
