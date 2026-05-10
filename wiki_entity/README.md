# Wiki Entity — Localized Knowledge Graph Pipeline

Automated pipeline for harvesting, structuring, and deploying a localized Knowledge Graph of Bangladeshi entities from Bengali Wikipedia and Wikidata. Achieves sub-500ms query latency by running a containerized QLever graph database entirely on local hardware.

## Pipeline Phases

| Phase | Directory | Description |
|-------|-----------|-------------|
| **Data Harvesting** | [`entity_builder/`](entity_builder/) | Crawls Bengali Wikipedia, extracts Wikidata relations, converts to RDF, indexes with QLever |
| **Agent & UI** | [`agent/`](agent/) | LLM-powered chatbot with ReAct tool-calling, Gradio web interface, entity verification CLI |

## Getting Started

### 1. Build the Knowledge Graph

See [entity_builder/README.md](entity_builder/README.md) for the full data pipeline:

1. `fetch_wiki.py` — Crawl Bengali Wikipedia categories (depth-limited, threaded)
2. `fetch_graph_mapping.py` — Query Wikidata SPARQL for entity relations
3. `convert_to_rdf.py` — Convert CSV to N-Triples
4. Load into QLever container (sub-5ms SPARQL queries)

### 2. Launch the Agent

See [agent/README.md](agent/README.md) for the chatbot interface:

1. Ensure vLLM is running on `localhost:5000` (qwen36 model)
2. Ensure QLever container is running on `localhost:7005`
3. `python app.py` — launches Gradio UI

## Architecture Highlights

- **Wikipedia-first traversal** — avoids Wikidata's incomplete geographical tagging
- **Local QLever indexing** — eliminates live API dependency for query responses
- **ReAct loop** — agent reasons step-by-step, calls tools, observes results
- **Bengali-first output** — all agent responses in formal, official Bengali
