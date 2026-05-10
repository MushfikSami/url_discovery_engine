# Architectural Blueprint: Localized Knowledge Graph Pipeline

## 1. Executive Summary

This document outlines the end-to-end systems architecture for harvesting, structuring, and deploying a localized, high-performance Knowledge Graph of Bangladeshi entities. The system achieves sub-500 millisecond retrieval times by completely bypassing live web-search and utilizing a containerized graph database (QLever) hosted entirely on local hardware.

The pipeline was engineered to overcome significant data-integrity hurdles — specifically the **"Floating Orphan"** problem in public graph databases where entities lack strict geographical tagging — by utilizing a **"Wikipedia-First"** traversal methodology.

---

## 2. Phase 1: Deep Graph Crawling (Data Acquisition)

**Objective:** Extract a comprehensive list of relevant entities (Nodes) directly from the human-curated Bengali Wikipedia Category Tree, bypassing the incomplete geographical tags inherent in standard Wikidata queries.

### Engineering Challenges & Solutions

#### The "Ontology Trap" (Category Drift)
Wikipedia is a highly interconnected web, not a strict top-down hierarchy. Traversing too deep into sub-categories causes semantic drift (e.g., moving from "History of Bangladesh" to "British India" to "Queen Victoria").

- **Architecture:** The crawler implements a strict Depth-Limited Traversal (optimized at Depth 2 or 3) to capture high-level, highly relevant entities while establishing a hard boundary against contextual drift.

#### API Firewalls & Rate Limiting (HTTP 429)
The Wikimedia Foundation employs enterprise-grade DDoS protection. Aggressive crawling triggers immediate, hard IP bans.

- **Architecture:** The system uses a Polite Concurrency Model. It restricts parallel execution to a strictly capped thread pool (maximum 5 concurrent workers). Furthermore, it implements an Exponential Backoff Strategy, allowing the crawler to autonomously pause, hold its queue, and dynamically retry if the server issues a rate-limit warning.

#### Pagination Constraints
API endpoints enforce a hard cap of 500 items per response, which is insufficient for massive "bucket" categories (e.g., "Villages in Bangladesh").

- **Architecture:** The extraction logic autonomously detects "Next Page" tokens in the API response payload, seamlessly paginating through massive folders until the entire branch is exhausted before closing the connection.

---

## 3. Phase 2: Graph Harvesting (Node-to-Edge Transformation)

**Objective:** Transform the flat CSV file of isolated entities (Nodes) extracted in Phase 1 into a highly structured, relational format (Edges/Triples) required by native SPARQL graph engines.

### Engineering Challenges & Solutions

#### The Relational Requirement
Graph databases do not ingest flat tables. They require multidimensional relational data defined as **"Subject → Predicate → Object"** (e.g., Dhaka → Located In → Bangladesh).

- **Architecture:** The system maps the extracted Wikipedia entities back to their underlying Wikidata Q-IDs. It then queries the Wikidata endpoint to extract all direct, "truthy" claims (established facts) associated with those IDs.

#### Query Timeouts & Truncation
Asking a public endpoint for the complete relational history of tens of thousands of items simultaneously will crash the query engine or result in silent data truncation.

- **Architecture:** The harvester employs a Direct Injection Batching Strategy. It slices the massive dataset into micro-batches of 100 entities at a time, queries them, and streams the results continuously into a local N-Triples (.nt) file. This ensures 100% data retention without triggering server timeouts.

---

## 4. Phase 3: High-Performance Indexing & Deployment

**Objective:** Compress the raw relational data into a heavily optimized mathematical index and deploy it as a live, queryable service.

### Engineering Challenges & Solutions

#### Graph Compression
Raw N-Triples text files are too slow for real-time querying. They must be mathematically sorted and indexed.

- **Architecture:** The pipeline utilizes QLever, a highly performant, C++ based graph engine from the University of Freiburg. An isolated Indexing Phase reads the N-Triples file, builds the internal vocabularies, and generates highly compressed `.dat` index files directly into the local host storage.

#### Containerized Security & Permissions
Docker containers inherently run with isolated root privileges, which can result in fatal "Permission Denied" errors when the container attempts to write the massive index files back to the host machine's hard drive.

- **Architecture:** The deployment uses Dynamic UID/GID Mapping. The host user's exact Linux credentials are automatically injected into the container at runtime, granting the graph engine seamless read/write access to the local storage volume without compromising system security.

#### Network Isolation
To prevent collisions with existing services on the host machine, the containerized database's internal port is mapped to an isolated, dedicated external port.

---

## 5. Phase 4: Validation & Health Check

**Objective:** Confirm the system architecture successfully captures historical nuance and meets the strict latency requirements for chatbot integration.

### Architectural Triumphs

| Achievement | Detail |
|-------------|--------|
| **Latency Eradication** | By severing reliance on live web-scraping, the local QLever endpoint processes complex SPARQL queries in ~3-5ms, vastly exceeding the sub-500ms requirement. |
| **Historical Timeline Integrity** | The graph successfully captures multi-dimensional facts that flat databases struggle with. Historical figures correctly return multiple, historically accurate citizenship tags (e.g., both Pakistan and Bangladesh for pre-1971 figures) without causing data schema conflicts. |
| **Deployment Readiness** | The system is now a persistent, local API endpoint, ready to receive parameterized SPARQL queries generated by the downstream LLM chatbot agent. |
