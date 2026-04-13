# es_engine.py

import numpy as np
from elasticsearch import Elasticsearch
import tritonclient.http as httpclient
from transformers import AutoTokenizer

# --- Replace your current config import with this ---
try:
    # When imported from outside (DeepEval)
    from elastic_search_engine.config import TRITON_URL, INDEX_NAME
except ModuleNotFoundError:
    # When run directly from inside this folder
    from config import TRITON_URL, INDEX_NAME
# ----------------------------------------------------

# Connect to Triton Server
try:
    triton_client = httpclient.InferenceServerClient(url=TRITON_URL)
    print(f"[+] Connected to Triton Server at {TRITON_URL}")
except Exception as e:
    print(f"[!] Triton Connection Error: {e}")

print("[*] Loading Gemma Tokenizer...")
tokenizer = AutoTokenizer.from_pretrained("google/embeddinggemma-300m")

# Connect to Elasticsearch
es = Elasticsearch("http://localhost:9200")


def get_query_embedding(text):
    """Tokenizes a single query and fetches its vector from Triton."""
    formatted_text = f"task: search result | query: {text}"
    encoded = tokenizer([formatted_text], padding=True, truncation=True, max_length=512, return_tensors="np")
    
    input_ids = encoded["input_ids"].astype(np.int64)
    attention_mask = encoded["attention_mask"].astype(np.int64)
    
    inputs = [
        httpclient.InferInput("input_ids", input_ids.shape, "INT64"),
        httpclient.InferInput("attention_mask", attention_mask.shape, "INT64")
    ]
    inputs[0].set_data_from_numpy(input_ids)
    inputs[1].set_data_from_numpy(attention_mask)
    
    outputs = [httpclient.InferRequestedOutput("sentence_embedding")]
    response = triton_client.infer(model_name="gemma_embedding", inputs=inputs, outputs=outputs)
    
    return response.as_numpy("sentence_embedding")[0].tolist()


def retrieve_context(query_text, query_vector, top_k=4):
    """Searches Elasticsearch using HYBRID search (Multi-Match + k-NN)."""
    search_query = {
        "knn": {
            "field": "chunk_vector",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": 50,
            "boost": 0.5 
        },
        "query": {
            "multi_match": {
                "query": query_text,
                # Boosting the summary and keywords fields to rank official definitions higher
                "fields": ["summary^2", "keywords^1.5", "raw_markdown^1"]
            }
        },
        "size": top_k,
        "_source": ["url", "summary", "raw_markdown"]
    }
    
    try:
        response = es.search(index=INDEX_NAME, body=search_query)
        hits = response["hits"]["hits"]
        contexts, sources = [], []
        
        for hit in hits:
            source_data = hit["_source"]
            url = source_data.get("url", "#")
            summary = source_data.get("summary", "সারসংক্ষেপ পাওয়া যায়নি")
            markdown = source_data.get("raw_markdown", "")
            
            # Format a structured context block for the LLM
            # Truncating markdown to ~3000 chars to prevent context window overflow
            context_block = f"Source URL: {url}\nSummary: {summary}\nContent Details:\n{markdown[:3000]}"
            contexts.append(context_block)
            
            if url != "#":
                sources.append(f"- [{url}]({url})")
                
        return "\n\n---\n\n".join(contexts), list(set(sources))
        
    except Exception as e:
        print(f"[!] Elasticsearch Error: {e}")
        return "", []