# Wiki Entity — Localized Knowledge Graph Pipeline

Automated pipeline for harvesting, structuring, and deploying a localized Knowledge Graph of Bangladeshi entities from Bengali Wikipedia and Wikidata.

## Architecture

See [architectural_blueprint.md](architectural_blueprint.md) for the full end-to-end system design.

## Pipeline Phases

### 1. Deep Graph Crawling
- **Script:** [`fetch_wiki.py`](fetch_wiki.py)
- Crawls Bengali Wikipedia category tree (e.g. `বিষয়শ্রেণী:বাংলাদেশ`) with depth-limited traversal (default: depth 2)
- Uses 5 concurrent workers with exponential backoff and pagination
- **Output:** `bangladesh_bn_wiki_true_massive.csv` — list of entities with Wikidata Q-IDs

### 2. Graph Harvesting
- **Script:** [`fetch_graph_mapping.py`](fetch_graph_mapping.py)
- Queries Wikidata SPARQL endpoint to extract relational triples (Subject → Predicate → Object)
- Batches entities in chunks of 50 to prevent server timeouts
- **Output:** `wikidata_massive_relational_map.csv` — entity-to-entity relationships

### 3. RDF Conversion
- **Script:** [`convert_to_rdf.py`](convert_to_rdf.py)
- Converts the relational CSV into N-Triples (.nt) format required by graph databases
- **Output:** `bd_graph.nt` — standardized RDF triples

### 4. Indexing & Deployment
- Uses **QLever** (C++ graph engine, University of Freiburg) to index `.nt` data
- Generates compressed `.dat` index files for sub-5ms SPARQL query latency
- Data files stored in `data/` (gitignored)

### 5. Validation
- **Script:** [`check_data.ipynb`](check_data.ipynb) — Jupyter notebook for inspecting and validating graph data

## File Reference

| File | Purpose |
|------|---------|
| `fetch_wiki.py` | Wikipedia category crawler |
| `fetch_graph_mapping.py` | Wikidata relationship harvester |
| `convert_to_rdf.py` | CSV → N-Triples converter |
| `check_data.ipynb` | Data validation notebook |
| `count.txt` | Entity count / documentation |
| `architectural_blueprint.md` | Full system architecture |

## Data Files

| File | Description |
|------|-------------|
| `bangladesh_bn_wiki_true_massive.csv` | Crawled entities with Q-IDs |
| `wikidata_massive_relational_map.csv` | Extracted triples |
| `bd_graph.nt` | N-Triples RDF file |
| `bd_index.*` | QLever compressed index files |

> `data/` directory is gitignored — contains generated index files and raw data.
