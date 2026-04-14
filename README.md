# URL Discovery Engine

A comprehensive system for discovering, crawling, indexing, and querying Bangladesh government websites (.gov.bd) with AI-powered content analysis and dual search system support.

## Features

- **Recursive Domain Discovery** - Automatically discovers .gov.bd domains from seed URLs
- **Async Web Crawling** - High-performance async crawling with content extraction
- **AI-Powered Analysis** - Generates summaries and keywords in Bengali using LLM
- **Dual Search Systems** - Tree Index (BM25) and Elasticsearch (Hybrid vector+lexical)
- **Formal Bengali Support** - All outputs in formal, official Bengali
- **Production-Ready** - Configuration management, validation, logging, linting

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 15+
- vLLM server (Qwen35 model)
- Triton Inference Server (Gemma embedding model)
- Elasticsearch 8.x

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/url_discovery_engine.git
cd url_discovery_engine

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Setup configuration
cp .env.example .env
# Edit .env with your actual values

# Run linting checks
nox -s lint

# Run type checking
nox -s type-check

# Run tests
nox -s test
```

### Running the Crawler

```bash
# Start PostgreSQL
docker-compose up -d

# Run BD recursive crawler
cd recursive_crawler/crawler
python bd_recursive_crawler.py

# Run liveness check
cd ..
python live_domains.py

# Run Gov BD crawler
cd gov_crawler_without_llm
python main.py
```

### Running the Agent

```bash
# Start vLLM and Triton servers
# (Assuming they run on localhost:5000 and localhost:7000)

cd recursive_crawler/agent
python app.py

# Access at http://localhost:7860
```

## Project Structure

```
url_discovery_engine/
├── src/url_discovery_engine/   # Main source code
│   ├── __init__.py
│   ├── config/                  # Configuration management
│   │   ├── __init__.py
│   │   └── settings.py          # Pydantic settings
│   └── logger.py                # Loguru logging setup
├── recursive_crawler/           # Original crawler modules
│   ├── crawler/
│   ├── gov_crawler_without_llm/
│   ├── banglapedia_crawler/
│   ├── agent/
│   ├── elastic_search_engine/
│   └── DeepEval/
├── docs/                        # Documentation
├── tests/                       # Test suite
├── config.yaml                  # YAML configuration
├── .env.example                 # Environment template
├── pyproject.toml              # Project metadata & deps
├── noxfile.py                  # Nox task runner
└── README.md
```

## Configuration

### Environment Variables (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL host | `localhost` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | `password` |
| `VLLM_BASE_URL` | vLLM server URL | `http://localhost:5000/v1` |
| `LLM_MODEL_NAME` | LLM model name | `qwen35` |
| `TRITON_URL` | Triton server URL | `localhost:7000` |
| `ES_HOST` | Elasticsearch host | `http://localhost:9200` |
| `CRAWLER_MAX_CONCURRENT_REQUESTS` | Max concurrent crawls | `30` |

### YAML Configuration (config.yaml)

All crawler settings, search parameters, and agent configurations can be overridden in `config.yaml`.

## Development

### Running Nox Sessions

```bash
# Run all quality checks
nox -s check

# Run linting
nox -s lint

# Run type checking
nox -s type-check

# Run tests
nox -s test

# Run tests with coverage
nox -s test_full

# Auto-fix formatting
nox -s format_fix

# Auto-fix linting
nox -s ruff_fix

# Clean generated files
nox -s clean
```

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run unit tests only
pytest tests/unit/ -v

# Run integration tests
pytest tests/integration/ -v

# Run with coverage
pytest tests/ --cov=url_discovery_engine
```

### Type Checking

```bash
# Type check entire codebase
mypy src/url_discovery_engine --strict

# Check specific file
mypy src/url_discovery_engine/config/settings.py
```

### Linting

```bash
# Run ruff
ruff check src/ tests/

# Run isort
isort --check src/ tests/

# Run black check
black --check src/ tests/
```

## Architecture

See [docs/README.md](docs/README.md) for system overview and [docs/architecture.md](docs/architecture.md) for detailed architecture diagrams.

## Documentation

| Document | Description |
|----------|-------------|
| [docs/README.md](docs/README.md) | Main index with quick links |
| [docs/architecture.md](docs/architecture.md) | System architecture with Mermaid diagrams |
| [docs/crawler/README.md](docs/crawler/README.md) | Domain discovery module |
| [docs/gov_crawler_without_llm/README.md](docs/gov_crawler_without_llm/README.md) | Gov BD content ingestion |
| [docs/banglapedia_crawler/README.md](docs/banglapedia_crawler/README.md) | Banglapedia crawler |
| [docs/agent/README.md](docs/agent/README.md) | Tree Index Agent |
| [docs/elastic_search_engine/README.md](docs/elastic_search_engine/README.md) | Elasticsearch search engine |
| [docs/deepeval/README.md](docs/deepeval/README.md) | Evaluation framework |

## License

Internal - Government of Bangladesh
