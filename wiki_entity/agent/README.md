# Bangladesh Government Service AI Agent

An official digital AI assistant for the Government of Bangladesh that provides accurate, verified information to citizens using a local knowledge graph and ReAct reasoning.

## Overview

This agent answers Bengali-language queries about Bangladesh government services, geography, and entities by:

1. Reasoning step-by-step (ReAct loop) via vLLM (`qwen36`)
2. Looking up entities in a local QLever knowledge graph backed by Bengali Wikipedia data
3. Returning responses in formal, official Bengali

## Architecture

```
app.py (Gradio UI)
    └── agent.py (ReAct loop with vLLM)
            └── tools.py (tool dispatcher + vLLM schema)
                    └── knowledge_tool.py (QLeverWikipediaTool: CSV index + SPARQL queries)
                            └── data/ (bangladesh_bn_wiki_true_massive.csv)

check_entity.py (standalone entity verifier)
config.py (OpenAI client + master system prompt)
```

## Files

| File | Purpose |
|------|---------|
| `agent.py` | Core ReAct loop — generates responses using vLLM with tool calls |
| `app.py` | Gradio web UI for the chat interface |
| `config.py` | OpenAI client config and the master system prompt |
| `tools.py` | Tool dispatcher and vLLM tool schema (`BD_GOV_TOOLS`) |
| `knowledge_tool.py` | `QLeverWikipediaTool` — fuzzy matches Bengali names to Wikidata Q-IDs, queries QLever SPARQL endpoint |
| `check_entity.py` | Standalone verification script — check if an entity exists in the CSV index and QLever DB |
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
python check_entity.py

# Direct query
python check_entity.py "ঢাকা"
```

This checks both the CSV index and the QLever database for the given Bengali entity name.

## Key Behavior

- **Language**: All responses are in formal, official Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা)
- **ReAct Loop**: The agent reasons through queries in up to 3 tool-call iterations
- **Zero Hallucination**: If data is missing from the knowledge graph, the agent admits it rather than inventing facts
- **Safety**: Queries involving self-harm, violence, illegal activity, or hacking are rejected with a standard Bengali refusal message
