# config.py
from openai import OpenAI

VLLM_BASE_URL = "http://localhost:5000/v1"
VLLM_API_KEY = "no-key"
VLLM_MODEL = "qwen36"

client = OpenAI(
    base_url=VLLM_BASE_URL,
    api_key=VLLM_API_KEY
)

# 🌐 NEW: Wikimedia API Compliant User-Agent
# Format: AppName/Version (YourEmail)
WIKI_USER_AGENT = "BDGovAgent/1.0 (mushfiksami7701@gmail.com) - Educational Bot"