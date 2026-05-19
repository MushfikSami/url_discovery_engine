# config.py
from openai import OpenAI

# 1. vLLM Configuration (From your previous architecture)
VLLM_BASE_URL = "http://localhost:5000/v1"
VLLM_API_KEY = "no-key"
VLLM_MODEL = "qwen36"

client = OpenAI(
    base_url=VLLM_BASE_URL,
    api_key=VLLM_API_KEY
)

# 2. SearXNG Configuration
# Change this to your local SearXNG port (usually 8080 or 8888)
SEARXNG_URL = "http://localhost:8080"