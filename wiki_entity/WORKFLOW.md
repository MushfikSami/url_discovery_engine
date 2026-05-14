# Wiki Entity — Complete Workflow Documentation

This document describes the end-to-end workflow of the `/wiki_entity` system: a localized Knowledge Graph pipeline for the Government of Bangladesh AI Assistant. The system harvests Bengali Wikipedia and Wikidata entities, indexes them in a local graph database, and serves them to an LLM-powered chatbot via a ReAct tool-calling agent.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BI-DIRECTIONAL SYSTEM                       │
│                                                                     │
│  ┌─ PHASE 1: DATA HARVESTING (entity_builder/) ──────────────────┐ │
│  │  Bengali Wikipedia → Wikidata SPARQL → RDF → QLever Index    │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌─ PHASE 2: AGENT & UI (agent/) ────────────────────────────────┐ │
│  │  Gradio UI → LLM (vLLM) → ReAct Loop → Tool Call → QLever   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌─ PHASE 3: GRAPH RAG (agent/) ─────────────────────────────────┐ │
│  │  XML Dump → Triton Embeddings → Elasticsearch (Vector)       │ │
│  │                          Neo4j (Graph)                       │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌─ PHASE 4: VALIDATION (agent/) ────────────────────────────────┐ │
│  │  CLI tool for verifying entities in CSV index & QLever DB    │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Data Harvesting (`entity_builder/`)

This phase builds the raw knowledge graph from public data sources.

### Step 1.1: Wikipedia Crawling

**File:** [entity_builder/fetch_wiki.py](entity_builder/fetch_wiki.py)

**Purpose:** Extract a comprehensive list of Bangladeshi entities from Bengali Wikipedia categories.

**Workflow:**
1. Starts from root category `বিষয়শ্রেণী:বাংলাদেশ` (Category:Bangladesh)
2. Performs **depth-limited traversal** (default: depth 2) through the Wikipedia category tree
3. For each category, queries the Wikimedia API to enumerate all pages within it
4. **Pagination handling:** Detects `continue` tokens in API responses and paginates through all results
5. **Rate limiting protection:** Uses max 5 concurrent workers with exponential backoff on HTTP 429 responses
6. Filters results to extract entity titles and their corresponding Wikidata Q-IDs
7. **Output:** `bangladesh_bn_wiki_true_massive.csv` — columns: `Bangla_Wikipedia_Title`, `Wikidata_ID`

**Why Wikipedia-first:** Bengali Wikipedia has richer, human-curated entity lists for Bangladesh than Wikidata's geotag-based queries. Wikidata's geographical tagging is incomplete for Bangladeshi entities.

### Step 1.2: Wikidata Graph Harvesting

**File:** [entity_builder/fetch_graph_mapping.py](entity_builder/fetch_graph_mapping.py)

**Purpose:** Transform flat entity list into relational triples (Subject → Predicate → Object).

**Workflow:**
1. Reads `bangladesh_bn_wiki_true_massive.csv` from Step 1.1
2. For each Q-ID, queries the Wikidata SPARQL endpoint to extract all direct claims (truthy predicates)
3. **Batching strategy:** Slices entities into micro-batches of 100 to prevent server timeouts
4. Extracts triples in format: `Q_ID → P_PREDICATE → Q_OBJECT_OR_LITERAL`
5. **Output:** `wikidata_massive_relational_map.csv` — columns: `Subject_ID`, `Relationship_ID`, `Object_ID`

### Step 1.3: RDF Conversion

**File:** [entity_builder/convert_to_rdf.py](entity_builder/convert_to_rdf.py)

**Purpose:** Convert the relational CSV into N-Triples format required by graph engines.

**Workflow:**
1. Reads `wikidata_massive_relational_map.csv`
2. Converts each row into a single RDF N-Triple:
   ```
   <http://www.wikidata.org/entity/Q12345> <http://www.wikidata.org/prop/direct/P31> <http://www.wikidata.org/entity/Q56789> .
   ```
3. **Output:** `bd_graph.nt` — standardized RDF N-Triples file

### Step 1.4: QLever Indexing

**Purpose:** Build compressed index for sub-5ms SPARQL query responses.

**Workflow:**
1. Uses **QLever** — a C++ graph database engine from the University of Freiburg
2. Reads `bd_graph.nt` and builds internal vocabularies
3. Generates compressed `.dat` index files
4. Deployed as a Docker container on `localhost:7005`
5. **Performance:** ~3-5ms per complex SPARQL query (well within sub-500ms requirement)

---

## Phase 2: Agent & Chat Interface (`agent/`)

This phase provides the user-facing chatbot powered by an LLM with tool-calling capabilities.

### Step 2.1: User Input

**File:** [agent/app.py](agent/app.py)

**Purpose:** Launch Gradio web interface.

**Workflow:**
1. User types a Bengali question in the chat UI (e.g., "ঢাকা সম্পর্কে বলুন?")
2. UI sends message to `generate_response()` function from [agent/agent.py](agent/agent.py)
3. Gradio UI launches on `0.0.0.0:7861` with `share=True` (public URL)

### Step 2.2: System Prompt & Tool Definition

**File:** [agent/config.py](agent/config.py)

**Purpose:** Define the LLM's behavior, identity, and available tools.

**Key Components:**
- **MASTER_SYSTEM_PROMPT:** Sets the LLM as "Official Digital AI Assistant for the Government of Bangladesh" with formal Bengali tone
- **BD_GOV_TOOLS:** Defines the `search_local_wikipedia_graph` tool with its schema (function name, description, parameters)

**Critical Rules in System Prompt:**
- Anti-bias rule: When asked "Who is the Prime Minister?", tool parameter must be "বাংলাদেশের প্রধানমন্ত্রী", NOT a specific politician's name
- Graph facts > text summary: If conflict between summary and graph facts, always use graph facts
- Safety protocol: Reject harmful/illegal queries with standard Bengali refusal

### Step 2.3: ReAct Loop Execution

**File:** [agent/agent.py](agent/agent.py)

**Purpose:** Orchestrate the LLM's reasoning → tool call → observe cycle.

**Workflow:**

```
User Message
    │
    ▼
Step 1: Initial LLM Call
    messages = [system_prompt, user_message]
    client.chat.completions.create(tools=BD_GOV_TOOLS, tool_choice="auto")
    │
    ▼
Has tool_calls?
    │
    ├── NO → Final Answer (confidence check, then yield)
    │
    └── YES → Enter ReAct Loop (max 3 iterations)
            │
            ▼
        Deduplicate parallel tool calls
            │
            ▼
        For each unique tool call:
            a. Execute: execute_tool(tool_name, tool_args)
            b. Append observation as "tool" message
            │
            ▼
        LLM observes results → reason again
            │
            ▼
        Has tool_calls? → Repeat loop (max 3 total)
            │
            ▼
        Confidence check → Yield final answer
```

**Detailed Breakdown:**

1. **History parsing:** Handles multiple Gradio history formats (dict, namedtuple, tuple)
2. **Initial call:** Sends system prompt + conversation history + user message to vLLM (`localhost:5000`), with `tools=BD_GOV_TOOLS` and `tool_choice="auto"`
3. **Tool call detection:** Checks `msg.tool_calls` for native tool invocation JSON
4. **Deduplication:** Uses `call_signature = f"{tool_name}_{tool_args}"` to avoid executing duplicate parallel calls
5. **Tool execution:** Passes tool name and JSON arguments to `execute_tool()` in [agent/tools.py](agent/tools.py)
6. **Observation injection:** Appends tool result as `role: "tool"` message with original `tool_call_id`
7. **Next iteration:** LLM receives observations and reasons again, either calling more tools or producing a final answer
8. **Confidence check:** Computes average token probability from logprobs. If below 85%, triggers anti-hallucination fallback message

### Step 2.4: Tool Execution

**File:** [agent/tools.py](agent/tools.py)

**Purpose:** Bridge between LLM tool calls and the actual database query.

**Workflow:**
1. `search_local_wikipedia_graph(entity_name)` is called by the LLM
2. It instantiates `GraphRAGWikipediaTool` from [agent/knowledge_tool.py](agent/knowledge_tool.py)
3. The tool performs:
   - **Vector search** in Elasticsearch (semantic matching of query)
   - **Graph traversal** in Neo4j (relational fact retrieval)
   - Returns combined result with `entity_matched`, `semantic_summary`, and `verified_graph_facts`

---

## Phase 3: Graph RAG Pipeline (`agent/`)

This phase augments the QLever database with vector-search capabilities and Neo4j graph storage.

### Step 3.1: XML Dump Processing

**File:** [agent/build_ingest_es.py](agent/build_ingest_es.py)

**Purpose:** Create vector-indexed Elasticsearch index from Bengali Wikipedia XML dump.

**Workflow:**
1. Reads `bnwiki-latest-pages-articles.xml.bz2` (Bengali Wikipedia dump)
2. Filters to only articles present in `bangladesh_bn_wiki_true_massive.csv`
3. For each matching article:
   - Extracts first 500 characters as summary (strips wiki markup)
   - Concatenates `title + " + " + summary` as embedding text
   - Sends to **Triton** (`localhost:7000/v2/models/gemma_embedding/infer`) for 768-dim embedding
   - Inserts into Elasticsearch with: `title`, `summary`, `q_id`, `text_vector`
4. **Batching:** Inserts in chunks of 100 documents via `helpers.bulk()`
5. **Output:** `wikipedia_bn_graphrag` Elasticsearch index

### Step 3.2: Neo4j Migration

**File:** [agent/migrate_to_neo4j.py](agent/migrate_to_neo4j.py)

**Purpose:** Store the knowledge graph facts in Neo4j for efficient graph traversal.

**Workflow:**
1. Reads `bangladesh_bn_wiki_true_massive.csv`
2. For each Q-ID, queries QLever (`localhost:7005`) for its relational edges
3. Extracts P-nodes (predicates) and Q-nodes (objects) from the SPARQL results
4. Converts to Cypher MERGE statements:
   ```cypher
   MERGE (s:Entity {qid: "Q123"}) ON CREATE SET s.label = "ঢাকা"
   MERGE (o:Entity {qid: "Q456"}) ON CREATE SET o.label = "বাংলাদেশ"
   MERGE (s)-[:P31]->(o)
   ```
5. Stores up to 100 edges per entity (LIMIT 100 in SPARQL query)
6. **Output:** Neo4j database with `:Entity` nodes and typed relationships

---

## Phase 4: Validation & Verification (`agent/`)

This phase provides CLI tools for verifying entities and database connectivity.

### Step 4.1: Entity Verification

**File:** [agent/check_qlevel.py](agent/check_qlevel.py)

**Purpose:** CLI tool to verify an entity exists in the CSV index and QLever database.

**Workflow:**
1. Takes entity name as CLI argument (e.g., `python check_qlevel.py "ঢাকা"`)
2. **Phase 1:** Loads CSV index, tries exact match, then fuzzy match (85% similarity)
3. **Phase 2:** Queries QLever for the entity's relational edges
4. Reports: entity name, Q-ID, Wikipedia URL, Wikidata URL, fact count, latency, sample edges

### Step 4.2: Q-ID Extraction

**File:** [agent/get_qids.py](agent/get_qids.py)

**Purpose:** Extract Q-IDs of specific entity types from QLever (e.g., all politicians).

**Workflow:**
1. Sends SPARQL query to QLever filtering by predicate (e.g., P106 = occupation = politician)
2. Extracts Q-IDs from results
3. Prints comma-separated list for use in downstream scripts

---

## Service Architecture

```
Service                    Port    Purpose                    File
────────────────────────────────────────────────────────────────────────
vLLM (qwen36)            5000    LLM inference             config.py
QLever (graph DB)         7005    SPARQL queries            entity_builder/
Triton (embedding)        7000    768-dim text embeddings   build_ingest_es.py
Elasticsearch             9200    Vector search + text      build_ingest_es.py
Neo4j                    7687    Graph traversal           knowledge_tool.py
Gradio UI                7861    Chat interface            app.py
```

---

## Data Flow Summary

```
┌───────────────────────┐
│ Bengali Wikipedia     │  Phase 1: entity_builder/
│ Wikidata SPARQL       │
└──────────┬────────────┘
           │ CSV + N-Triples
           ▼
┌───────────────────────┐
│ QLever Index           │  Phase 1: graph DB
│ (SPARQL, localhost:7005)
└──────────┬────────────┘
           │ SPARQL results
           ▼
┌───────────────────────┐
│ Elasticsearch          │  Phase 3: build_ingest_es.py
│ Neo4j                  │  Phase 3: migrate_to_neo4j.py
│ (Vector + Graph)       │
└──────────┬────────────┘
           │ search_entity() result
           ▼
┌───────────────────────┐
│ LLM (vLLM:5000)        │  Phase 2: agent.py
│ ReAct Loop             │  Phase 2: tools.py
└──────────┬────────────┘
           │ Final Answer (Bengali)
           ▼
┌───────────────────────┐
│ Gradio UI (:7861)      │  Phase 2: app.py
│ User                   │
└───────────────────────┘
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Wikipedia-first traversal | Wikidata geotagging is incomplete for Bangladeshi entities |
| Depth-limited crawling (depth 2) | Prevents semantic drift (e.g., "History of Bangladesh" → "British India" → "Queen Victoria") |
| Local QLever indexing | Eliminates live API dependency; achieves ~3-5ms query latency |
| ReAct tool-calling pattern | Enables the LLM to reason step-by-step, call tools, observe results |
| Confidence check (85% threshold) | Anti-hallucination kill switch; rejects low-confidence answers |
| Bengali-first output | All responses in formal, official Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা) |
| Triton Gemma embeddings (768-dim) | On-device embedding generation without external API calls |
| Neo4j + Elasticsearch hybrid | ES for semantic/text search, Neo4j for relational/graph traversal |

---

## File Reference

| File | Directory | Role |
|------|-----------|------|
| `entity_builder/fetch_wiki.py` | entity_builder | Wikipedia category crawler |
| `entity_builder/fetch_graph_mapping.py` | entity_builder | Wikidata SPARQL harvester |
| `entity_builder/convert_to_rdf.py` | entity_builder | CSV → N-Triples converter |
| `entity_builder/architectural_blueprint.md` | entity_builder | System architecture design |
| `agent/app.py` | agent | Gradio web interface |
| `agent/agent.py` | agent | LLM ReAct loop orchestrator |
| `agent/config.py` | agent | System prompt + tool schema |
| `agent/tools.py` | agent | Tool dispatcher + definition |
| `agent/knowledge_tool.py` | agent | GraphRAG tool (ES + Neo4j) |
| `agent/build_ingest_es.py` | agent | Elasticsearch index builder |
| `agent/migrate_to_neo4j.py` | agent | Neo4j graph migration |
| `agent/check_qlevel.py` | agent | Entity verification CLI |
| `agent/get_qids.py` | agent | Q-ID extraction from QLever |
