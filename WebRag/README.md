# WebRag

A lightweight pipeline that converts a natural-language question into clean, structured Markdown context by combining an LLM query optimizer, Wikipedia's OpenSearch API, and IBM Docling's document parser. Designed primarily for Bengali-language queries with full English support.

## How It Works

```
User Question (Bengali or English)
         |
         v
[ Fanout ]  LLM (vLLM) converts natural language into an optimized Wikipedia search phrase
         |
         v
[ Search ]  MediaWiki OpenSearch API returns top matching URL + fallback suggestions
         |
         v
[ Parser ]  IBM Docling scrapes the URL and converts it to clean Markdown
         |
         v
   final_context.md
```

### Step 1: Fanout (Intent to Keyword)

[fanout.py](fanout.py) sends the user's question to a local vLLM instance (`qwen36` model). A zero-temperature prompt with a strict system instruction extracts a precise Wikipedia search phrase, stripping conversational filler like "who is", "tell me about", "what is the history of". Bengali queries are preserved in their original script. If the LLM is unavailable, it falls back to using the raw user prompt.

```python
# Key parameters
temperature=0.0       # Deterministic — same input always produces the same output
max_tokens=20         # Keeps output tight (just the search phrase)
fallback_to_raw=True  # If vLLM fails, use user's original query
```

### Step 2: Search (Keyword to URL)

[search.py](search.py) queries the **MediaWiki OpenSearch API** directly (no SearXNG proxy needed). Key behavior:

- **Auto language routing**: Detects Bengali Unicode characters (`ঀ-৿`) in the query and routes to `bn.wikipedia.org`; otherwise routes to `en.wikipedia.org`
- **Top-3 fetching**: Requests up to 3 suggestions via `limit=3`
- **Fallback suggestions**: Returns the top URL plus alternative titles (2nd and 3rd results) for fallback attempts
- **Namespace filter**: Only searches standard articles (`namespace=0`), excluding talk pages and user pages

```python
# API call details
action="opensearch"
limit=3
namespace=0          # Standard articles only
format="json"
timeout=5.0s
# Response format: ["Query", [Title1, Title2, Title3], [Desc1, Desc2, Desc3], [URL1, URL2, URL3]]
```

### Step 3: Parser (URL to Markdown)

[parser.py](parser.py) uses IBM Docling's `DocumentConverter` to scrape any URL and export its content as clean Markdown. The process:

1. Downloads raw HTML via `requests` with a Wikimedia-compliant User-Agent header (`BDGovAgent/1.0`)
2. Saves the HTML to a temporary file (Docling requires a file path, not raw content)
3. Runs Docling's converter to extract structured Markdown
4. Cleans up the temporary file in a `finally` block

```python
# Pipeline stages
1. requests.get(url, timeout=10.0)  # Download HTML
2. tempfile.NamedTemporaryFile()    # Write to temp file
3. DocumentConverter().convert()    # Parse with Docling
4. result.document.export_to_markdown()  # Extract Markdown
5. os.remove(tmp_path)              # Clean up temp file
```

### Orchestrator

[main.py](main.py) ties the three steps together in `execute_webrag_pipeline(user_input)`. Returns the final Markdown string (or an error message if no URL is found). Includes `__main__` block for standalone testing.

## Dependencies

| Component | Requirement | Purpose |
|-----------|-------------|---------|
| vLLM | Running on `localhost:5000` | Local LLM inference (model: `qwen36`) |
| Python `openai` | `pip install openai` | vLLM client SDK (compatible OpenAI API) |
| Python `requests` | `pip install requests` | HTTP client for Wikipedia API + HTML fetching |
| IBM Docling | `pip install docling` | Document-to-Markdown converter |

## Setup

### 1. Install Python dependencies

```bash
pip install openai requests docling
```

### 2. Configure

Edit [config.py](config.py) if your services run on different hosts or ports:

- `VLLM_BASE_URL` — vLLM server address (default: `http://localhost:5000/v1`)
- `VLLM_API_KEY` — API key (default: `"no-key"` for local vLLM)
- `VLLM_MODEL` — Model name (default: `qwen36`)
- `WIKI_USER_AGENT` — Wikimedia API-compliant User-Agent (format: `AppName/Version (Email)`)

### 3. Start vLLM

Ensure your local vLLM server is running on the configured `VLLM_BASE_URL`:

```bash
# Example — adjust model path and ports to your setup
vllm serve <model-name> --port 5000
```

### 4. Run the pipeline

```bash
python main.py
```

This runs a test query ("শহীদ মিনার কে নকশা করেছেন?" — "Who designed the National Martyrs' Monument?") and prints the Markdown output to stdout.

## File Structure

```
WebRag/
  config.py                # vLLM connection settings, OpenAI client, User-Agent string
  fanout.py                # LLM-based query optimization (extracts search phrase)
  search.py                # MediaWiki OpenSearch API lookup (auto language routing)
  parser.py                # Docling URL-to-Markdown conversion
  main.py                  # Pipeline orchestrator (fanout → search → parse)
  final_context.md         # Generated output (last pipeline run)
```

## Architecture Notes

- **No external APIs**: All components (vLLM, Docling) run locally. Wikipedia API calls go directly to `en.wikipedia.org` or `bn.wikipedia.org`.
- **Deterministic fanout**: `temperature=0.0` ensures the LLM produces the same search phrase every time for the same input.
- **Graceful degradation**: If vLLM is down, the raw user prompt is used as-is. If the MediaWiki API is unreachable, the pipeline returns `None` cleanly.
- **Language auto-detection**: Bengali Unicode detection (`ঀ-৿`) automatically routes queries to the correct Wikipedia edition.
- **Direct API access**: Uses MediaWiki OpenSearch API directly — no SearXNG proxy needed, reducing infrastructure complexity.
- **Wikipedia-only**: The OpenSearch API targets a single Wikipedia edition per query, keeping results focused and relevant.
