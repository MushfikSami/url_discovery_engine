# WebRag

A lightweight pipeline that converts a natural-language question into clean, structured Markdown context by combining an LLM query optimizer, a privacy-friendly search engine, and IBM Docling's document parser.

## How It Works

```
User Question
     |
     v
[ Fanout ]  LLM (vLLM) converts natural language into an optimized Wikipedia search phrase
     |
     v
[ Search ]  SearXNG queries Wikipedia and returns the top matching URL
     |
     v
[ Parser ]  IBM Docling scrapes the URL and converts it to clean Markdown
     |
     v
  final_context.md
```

### Step 1: Fanout (Intent to Keyword)

[fanout.py](fanout.py) sends the user's question to a local vLLM instance. A zero-temperature prompt extracts a precise Wikipedia search phrase, stripping conversational filler. If the LLM is unavailable, it falls back to using the raw user prompt.

### Step 2: Search (Keyword to URL)

[search.py](search.py) queries a local SearXNG instance restricted to the Wikipedia engine. It first checks standard results, then falls back to infobox matches if no direct results are found. Returns the top Wikipedia URL or `None`.

### Step 3: Parser (URL to Markdown)

[parser.py](parser.py) uses IBM Docling's `DocumentConverter` to scrape any URL and export its content as clean Markdown. This replaces brittle HTML parsing with a robust document-to-markdown pipeline.

### Orchestrator

[main.py](main.py) ties the three steps together in `execute_webrag_pipeline(user_input)`. It prints progress markers at each stage and writes the result to `final_context.md`.

## Dependencies

| Component | Requirement | Purpose |
|-----------|-------------|---------|
| vLLM | Running on `localhost:5000` | Local LLM inference (model: `qwen36`) |
| SearXNG | Running on `localhost:8080` | Self-hosted, privacy-friendly meta-search engine |
| Python `openai` | `pip install openai` | vLLM client SDK (compatible OpenAI API) |
| Python `requests` | `pip install requests` | HTTP client for SearXNG queries |
| IBM Docling | `pip install docling` | Document-to-Markdown converter |

## Setup

### 1. Install Python dependencies

```bash
pip install openai requests docling
```

### 2. Configure

Edit [config.py](config.py) if your services run on different hosts or ports:

- `VLLM_BASE_URL` — vLLM server address (default: `http://localhost:5000/v1`)
- `SEARXNG_URL` — SearXNG server address (default: `http://localhost:8080`)

### 3. Deploy SearXNG

A Docker Compose setup is included at [searxng_setup/](searxng_setup/).

```bash
cd searxng_setup
docker compose up -d
```

This spins up a SearXNG instance with:
- Wikipedia as the default and only enabled engine
- JSON output format enabled (required by [search.py](search.py))
- Exposed on port 8080

Configuration:

| File | Purpose |
|------|---------|
| [docker-compose.yml](searxng_setup/docker-compose.yml) | Container definition, port mapping, volume mount for settings |
| [settings.yml](searxng_setup/searxng/settings.yml) | SearXNG config — safe search off, JSON+HTML output, Wikipedia engine only |

### 4. Run the pipeline

```bash
python main.py
```

This runs a test query ("Who is the current Prime Minister of Bangladesh?") and writes the Markdown output to `final_context.md`.

Replace the test query in `__main__` with your own input, or import `execute_webrag_pipeline` from another script.

## File Structure

```
WebRag/
  config.py                # vLLM and SearXNG connection settings
  fanout.py                # LLM-based query optimization
  search.py                # SearXNG Wikipedia search
  parser.py                # Docling URL-to-Markdown conversion
  main.py                  # Pipeline orchestrator
  final_context.md         # Generated output (last run)
  searxng_setup/
    docker-compose.yml     # SearXNG container definition
    searxng/
      settings.yml         # SearXNG configuration
```

## Architecture Notes

- **No external APIs**: All components (vLLM, SearXNG, Docling) run locally. No data leaves your machine.
- **Deterministic fanout**: `temperature=0.0` ensures the LLM produces the same search phrase every time for the same input.
- **Graceful degradation**: If vLLM is down, the raw user prompt is used as-is. If SearXNG is unreachable, the pipeline returns `None` cleanly.
- **Wikipedia-only**: SearXNG is configured to query only Wikipedia, keeping results focused and relevant.
