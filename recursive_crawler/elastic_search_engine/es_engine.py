# es_engine.py

import numpy as np
from elasticsearch import Elasticsearch
import tritonclient.http as httpclient
from transformers import AutoTokenizer

from config import TRITON_URL, INDEX_NAME

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


def retrieve_context(query_text, query_vector, top_k=5):
    """Searches Elasticsearch using HYBRID search (BM25 + k-NN)."""
    search_query = {
        "knn": {
            "field": "chunk_vector",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": 50,
            "boost": 0.5 
        },
        "query": {
            "match": {
                "chunk_text": {
                    "query": query_text,
                    "boost": 1.5 
                }
            }
        },
        "size": top_k,
        "_source": ["chunk_text", "url", "site_title"]
    }
    try:
        response = es.search(index=INDEX_NAME, body=search_query)
        hits = response["hits"]["hits"]
        contexts, sources = [], []
        
        for hit in hits:
            source_data = hit["_source"]
            contexts.append(source_data.get("chunk_text", ""))
            
            title = source_data.get("site_title", "").strip()
            if not title or len(title) < 3 or "```" in title:
                title = "Official BD Government Document"
                
            url = source_data.get("url", "#")
            if url != "#":
                sources.append(f"- [{title}]({url})")
                
        return "\n\n".join(contexts), list(set(sources))
    except Exception as e:
        print(f"[!] Elasticsearch Error: {e}")
        return "", []