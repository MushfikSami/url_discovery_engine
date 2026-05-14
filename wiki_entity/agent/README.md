# Bangladesh Government Service AI Agent

An official digital AI assistant for the Government of Bangladesh that provides accurate, verified information to citizens using a local knowledge graph and ReAct reasoning.

## Overview

This agent answers Bengali-language queries about Bangladesh government services, geography, and entities by:

1. Reasoning step-by-step (ReAct loop) via vLLM (`qwen36`)
2. Looking up entities in a local Elasticsearch knowledge graph with Triton-powered embeddings, backed by Bengali Wikipedia data
3. Returning responses in formal, official Bengali

## Architecture

```
app.py (Gradio UI)
    └── agent.py (ReAct loop with vLLM)
            └── tools.py (tool dispatcher + vLLM schema)
                    └── knowledge_tool.py (GraphRAGWikipediaTool: ES hybrid search + Triton embeddings + QLever SPARQL)
                            └── data/ (bangladesh_bn_wiki_true_massive.csv)

build_ingest_es.py (XML dump parser + Triton embedding generator + ES index builder)
migrate_to_neo4j.py (Wikidata → Neo4j graph migration via QLever SPARQL)
get_qids.py (Q-ID batch extractor from QLever — queries by Wikidata property)
check_qlevel.py (standalone entity verifier — CSV index + QLever DB)
test_es.py (hybrid search tester — validates ES index with sample query)
config.py (OpenAI client + master system prompt)
```

## Files

| File | Purpose |
|------|---------|
| `agent.py` | Core ReAct loop — generates responses using vLLM with tool calls |
| `app.py` | Gradio web UI for the chat interface |
| `config.py` | OpenAI client config and the master system prompt |
| `tools.py` | Tool dispatcher and vLLM tool schema (`BD_GOV_TOOLS`) |
| `knowledge_tool.py` | `GraphRAGWikipediaTool` — Triton embeddings, ES hybrid search (semantic 80% + lexical 20%), QLever SPARQL graph retrieval |
| `build_ingest_es.py` | Ingestion pipeline — parses Bengali Wikipedia XML dump, generates embeddings via Triton, bulk-loads into Elasticsearch |
| `check_qlevel.py` | Standalone verification — fuzzy-matches Bengali names against CSV index, queries QLever for entity facts |
| `test_es.py` | ES index verifier — checks document count, runs hybrid search test query with typo tolerance |
| `migrate_to_neo4j.py` | Graph migration — queries QLever SPARQL for Wikidata facts, loads into Neo4j with `MERGE` semantics |
| `get_qids.py` | Q-ID batch extractor — queries QLever for entities matching a Wikidata property (e.g., all politicians via P106) |
| `data/` | Bengali Wikipedia title-to-QID mapping CSV |

## Prerequisites

- **vLLM server** running on `localhost:5000` with model `qwen36` (configured in [config.py](config.py))
- **QLever database** running on `localhost:7005` (Docker container)
- CSV data file: `data/bangladesh_bn_wiki_true_massive.csv`

## Usage

### Launch the UI

```bash
python app.py
```

The Gradio interface starts at `http://localhost:7861` (with `share=True` for public access).

### Verify an entity

```bash
# Interactive mode
python check_qlevel.py

# Direct query
python check_qlevel.py "ঢাকা"
```

Checks the CSV index and QLever database for the given Bengali entity name.

### Test ES index

```bash
python test_es.py
```

Validates the Elasticsearch index by checking document count and running a hybrid search query.

### Ingest Wikipedia data into Elasticsearch

```bash
python build_ingest_es.py
```

Parses the Bengali Wikipedia XML dump (`data/bnwiki-latest-pages-articles.xml.bz2`), filters to Bangladesh entities from the CSV index, generates 768-dim embeddings via Triton (`localhost:7000`), and bulk-loads into Elasticsearch (`localhost:9200`).

### Migrate Wikidata facts to Neo4j

```bash
python migrate_to_neo4j.py
```

Queries QLever (`localhost:7005`) for all Wikidata property facts (subject-predicate-object triples) for the Bangladesh entity set and loads them into Neo4j (`localhost:7687`) as a knowledge graph with `MERGE` semantics.

### Extract Q-IDs by property

```bash
python get_qids.py
```

Runs a SPARQL query against QLever to extract Q-IDs matching a Wikidata property (default: all politicians via P106). Useful for verifying the entity set before ingestion.

## Key Behavior

- **Language**: All responses are in formal, official Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা)
- **ReAct Loop**: The agent reasons through queries in up to 3 tool-call iterations
- **Zero Hallucination**: If data is missing from the knowledge graph, the agent admits it rather than inventing facts
- **Safety**: Queries involving self-harm, violence, illegal activity, or hacking are rejected with a standard Bengali refusal message
