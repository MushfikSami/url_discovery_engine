# URL Discovery Engine - Documentation

## Overview

The **URL Discovery Engine** is a comprehensive system for discovering, crawling, indexing, and querying Bangladesh government websites (.gov.bd). It features multiple crawling pipelines, AI-powered content analysis, and two distinct search systems for answering user queries in formal Bengali.

---

## Quick Links

| Component | Description | Documentation |
|-----------|-------------|---------------|
| [Architecture](architecture.md) | System architecture overview | [Link](architecture.md) |
| [Crawler System](crawler/README.md) | Recursive domain discovery | [Link](crawler/README.md) |
| [Gov BD Pipeline](gov_crawler_without_llm/README.md) | Government site content ingestion | [Link](gov_crawler_without_llm/README.md) |
| [Banglapedia Pipeline](banglapedia_crawler/README.md) | Banglapedia encyclopedia crawler | [Link](banglapedia_crawler/README.md) |
| [Tree Index Agent](agent/README.md) | Hierarchical tree-based search agent | [Link](agent/README.md) |
| [Elasticsearch Engine](elastic_search_engine/README.md) | Hybrid vector+lexical search system | [Link](elastic_search_engine/README.md) |
| [DeepEval](deepeval/README.md) | System evaluation framework | [Link](deepeval/README.md) |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         URL Discovery Engine                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │   BD Crawler     │    │  Gov Crawler     │    │ Banglapedia      │  │
│  │   (Recursive)    │───▶│  (With LLM)      │───▶│  Crawler         │  │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘  │
│         │                      │                      │                  │
│         └──────────────────────┼──────────────────────┘                  │
│                                │                                         │
│                                ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     PostgreSQL Database (bd_gov_db)               │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐   │   │
│  │  │  websites   │  │ website_links│  │   banglapedia_pages    │   │   │
│  │  │  (URLs +    │  │  (Graph      │  │                        │   │   │
│  │  │   Summary)  │  │   Links)     │  │                        │   │   │
│  │  └─────────────┘  └──────────────┘  └────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                │                                         │
│                                ├──────────────────┬──────────────────────┤
│                                ▼                  ▼                      │
│  ┌─────────────────────────┐  ┌─────────────────────────────────────┐   │
│  │  Tree Index Agent       │  │    Elasticsearch Engine             │   │
│  │  (BM25 + Tree Search)   │  │    (Hybrid Vector + Lexical)        │   │
│  │  ─────────────────────  │  │    ─────────────────────────────    │   │
│  │  - Hierarchical JSON    │  │    - Elasticsearch 8.x              │   │
│  │  - BM25 Lexical Search  │  │    - Triton Inference Server        │   │
│  │  - ReAct Agent Loop     │  │    - Gemma Embedding Model          │   │
│  │  - Tree Index Structure │  │    - Hybrid Search                  │   │
│  └─────────────────────────┘  └─────────────────────────────────────┘   │
│                                │                  │                      │
│                                └────────┬───────┘                        │
│                                         ▼                                │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Gradio Chat Interface                          │   │
│  │              (Agent app.py - Port 7860)                           │   │
│  │         (Elasticsearch app.py - separate deployment)              │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Language** | Python 3.x |
| **Database** | PostgreSQL 15 (via Docker) |
| **Search Engine** | Elasticsearch 8.x |
| **ML Inference** | vLLM (Qwen35), Triton Server (Gemma Embedding) |
| **Crawler Framework** | crawl4ai, aiohttp |
| **Search Algorithms** | BM25, Hybrid (Vector + Lexical) |
| **Evaluation** | DeepEval |
| **UI** | Gradio |

---

## Key Concepts

### 1. Two Search Systems

The engine implements **two distinct search/answering systems** that can be evaluated against each other:

| Feature | **Tree Index Agent** | **Elasticsearch Engine** |
|---------|---------------------|--------------------------|
| **Data Source** | Hierarchical JSON tree | Elasticsearch index |
| **Search Method** | BM25 on tree nodes | Hybrid (Vector + Multi-Match) |
| **Best For** | Navigating official structure | General queries & procedures |
| **Index Build** | `db_to_md.py` + PageIndex | `ingest_to_es.py` |

### 2. Pipeline Stages

```
Stage 1: Discovery
  └── bd_recursive_crawler.py discovers .gov.bd domains

Stage 2: Liveness Check
  └── live_domains.py checks which domains are active

Stage 3: Content Crawling
  ├── gov_crawler_without_llm/ - Crawls government sites
  └── banglapedia_crawler/ - Crawls Banglapedia articles

Stage 4: AI Enrichment (bd_gov_db only)
  ├── crawler/bd_recursive_crawler.py with LLM
  └── Generates summaries & keywords in Bengali

Stage 5: Link Extraction
  ├── crawler/extract_links.py
  └── Builds website_links graph table

Stage 6: Indexing
  ├── Tree Index: Export to JSON → BM25 index
  └── ES Index: Hybrid search with embeddings

Stage 7: Query Answering
  ├── Tree Agent: agent/app.py
  └── ES Agent: elastic_search_engine/app.py (if exists)

Stage 8: Evaluation
  └── DeepEval: Compare both systems
```

---

## Directory Structure

```
url_discovery_engine/
├── __init__.py
├── docs/                          # This documentation
├── recursive_crawler/
│   ├── crawler/                   # BD recursive crawler + helpers
│   │   ├── bd_recursive_crawler.py   # Main recursive domain discover
│   │   ├── link_extractor.py         # Extract links from markdown
│   │   ├── duplicate_filter.py       # Filter verified URLs
│   │   ├── live_domains.py           # Check domain liveness
│   │   └── main_crawler.py           # Filter verified URLs
│   │
│   ├── gov_crawler_without_llm/   # Gov BD content ingestion
│   │   ├── main.py
│   │   ├── crawler.py
│   │   ├── database.py
│   │   ├── loader.py
│   │   └── config.py
│   │
│   ├── banglapedia_crawler/       # Banglapedia encyclopedia
│   │   ├── main.py
│   │   ├── crawler.py
│   │   ├── gatherer.py
│   │   ├── database.py
│   │   └── config.py
│   │
│   ├── agent/                     # Tree Index ReAct Agent
│   │   ├── app.py                    # Gradio chat interface
│   │   ├── tree_index.py             # BM25 tree search
│   │   ├── db_query.py               # DB export utility
│   │   ├── db_to_md.py               # Export to markdown
│   │   ├── utils.py                  # Tree utilities
│   │   └── config.py                 # System prompts
│   │
│   ├── elastic_search_engine/     # Hybrid search engine
│   │   ├── es_engine.py              # Search functions
│   │   ├── setup_es.py               # Index creation
│   │   ├── ingest_to_es.py           # Tree ingestion
│   │   ├── ingest_to_es_from_postgres.py  # DB ingestion
│   │   ├── config.py                 # ES configuration
│   │   ├── check_data.py             # Test queries
│   │   └── reset_es.py               # Index deletion
│   │
│   ├── DeepEval/                  # System evaluation
│   │   ├── main_eval.py              # Evaluation runner
│   │   ├── eval_adapters.py          # System A/B adapters
│   │   ├── eval_helpers.py           # Judge utilities
│   │   ├── eval_config.py            # Prompts & config
│   │   └── queries.csv               # Test queries
│   │
│   ├── docker-compose.yml          # PostgreSQL setup
│   └── output.txt                  # Agent output log
│
└── .gitignore
```

---

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- vLLM server running on `localhost:5000`
- Triton Inference Server on `localhost:7000`
- Elasticsearch on `localhost:9200`

### Quick Start

1. **Start PostgreSQL:**
   ```bash
   cd recursive_crawler
   docker-compose up -d
   ```

2. **Run a crawler:**
   ```bash
   # BD Recursive Crawler
   cd crawler && python bd_recursive_crawler.py

   # Gov BD Pipeline
   cd gov_crawler_without_llm && python main.py

   # Banglapedia Pipeline
   cd banglapedia_crawler && python main.py
   ```

3. **Launch Tree Agent:**
   ```bash
   cd agent && python app.py
   # Access at http://localhost:7860
   ```

---

## Configuration

### Database Configuration

All crawlers use PostgreSQL with these default credentials:

| Parameter | Value |
|-----------|-------|
| Host | `localhost` |
| Port | `5432` |
| User | `postgres` |
| Password | `password` |
| DB (Gov BD) | `bd_gov_db` |
| DB (Banglapedia) | `banglapedia_db` |

### ML Services

| Service | URL | Purpose |
|---------|-----|---------|
| vLLM | `http://localhost:5000/v1` | Qwen35 LLM |
| Triton | `localhost:7000` | Gemma Embeddings |
| Elasticsearch | `http://localhost:9200` | Hybrid search |

---

## Contributing

See individual module documentation for specific contribution guidelines.

---

## License

Internal project - Government of Bangladesh Digital Infrastructure

---

*Last Updated: April 2026*
