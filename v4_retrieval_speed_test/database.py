# database.py
from elasticsearch import Elasticsearch
from config import ES_HOST

def get_es_client():
    """Establishes and verifies the connection to Elasticsearch."""
    print("🔌 Connecting to Elasticsearch...")
    es = Elasticsearch(ES_HOST)
    
    if not es.ping():
        raise ConnectionError(f"🚨 Cannot connect to Elasticsearch at {ES_HOST}. Is Docker running?")
    
    print("✅ Connection Established.")
    return es