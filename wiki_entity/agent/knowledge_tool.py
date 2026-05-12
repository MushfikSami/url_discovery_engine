import requests
import json
from elasticsearch import Elasticsearch
from transformers import AutoTokenizer
import numpy as np # (Make sure to import numpy as well)
tokenizer = AutoTokenizer.from_pretrained("google/embeddinggemma-300m")

class GraphRAGWikipediaTool:
    def __init__(self, es_url="http://localhost:9200", qlever_url="http://localhost:7005"):
        self.qlever_url = qlever_url
        self.index_name = "wikipedia_bn_graphrag"
        
        # Triton configuration
        self.triton_url = "http://localhost:7000/v2/models/gemma_embedding/infer" # Update if needed
        
        # Connect to existing Elasticsearch container
        self.es = Elasticsearch(es_url)
        print("🔗 Connected to Elasticsearch and Triton Inference Server.")

    def get_triton_embedding(self, text: str) -> list:
        """Fetches embeddings from the local Triton Inference Server."""
        payload = {
            "inputs": [
                {
                    "name": "text", # Update if your input tensor is named differently
                    "shape": [1, 1],
                    "datatype": "BYTES",
                    "data": [[text]]
                }
            ]
        }
        try:
            response = requests.post(self.triton_url, json=payload, timeout=2.0)
            if response.status_code == 200:
                outputs = response.json().get("outputs", [])
                if outputs:
                    return outputs[0].get("data", [])
            return []
        except:
            return []

    def search_entity(self, user_query: str) -> str:
        print(f"\n[GraphRAG] 1. Initiating Search for: '{user_query}'")
        
        # --- STEP 1: EMBED QUERY VIA TRITON ---
        # --- MODULAR CALL ---
        query_vector = self.get_triton_embedding(user_query)
        
        if not query_vector:
            return "RESULT_NOT_FOUND: Failed to generate embedding from Triton."

        # --- TRUE PARALLEL HYBRID SEARCH (ES 8.x) ---
        es_query = {
            "size": 1, # We only need the top result for the agent
            "knn": {
                "field": "text_vector",
                "query_vector": query_vector,
                "k": 10,
                "num_candidates": 100,
                "boost": 0.8 # Semantic Meaning acts as the primary driver (80%)
            },
            "query": {
                "match": {
                    "title": {
                        "query": user_query,
                        "fuzziness": "AUTO",
                        "boost": 0.2 # Exact text match acts as a secondary booster (20%)
                    }
                }
            }
        }
        
        try:
            es_response = self.es.search(index=self.index_name, body=es_query)

            hits = es_response['hits']['hits']
            
            if not hits:
                print("❌ [GraphRAG] Miss! Triggering Kill Switch.")
                return "RESULT_NOT_FOUND"
                
            best_match = hits[0]['_source']
            entity_title = best_match['title']
            q_id = best_match['q_id']
            summary_text = best_match['summary']
            
            print(f"[GraphRAG] 2. Found Context: {entity_title} ({q_id})")
            
        except Exception as e:
            return f"RESULT_NOT_FOUND: ES Error: {e}"

        # --- STEP 3: EXACT GRAPH RETRIEVAL (QLEVER) ---
        print(f"[GraphRAG] 3. Pinging Graph for Edges...")
        sparql_query = f"SELECT ?predicate ?object WHERE {{ <http://www.wikidata.org/entity/{q_id}> ?predicate ?object }}"
        
        clean_edges = []
        try:
            ql_response = requests.get(
                self.qlever_url, 
                params={"query": sparql_query}, 
                headers={"Accept": "application/sparql-results+json"},
                timeout=1.0 
            )
            
            if ql_response.status_code == 200:
                results = ql_response.json()['results']['bindings']
                for row in results:
                    p = row['predicate']['value'].split('/')[-1]
                    o = row['object']['value'].split('/')[-1]
                    clean_edges.append({p: o})
        except Exception as e:
            print(f"⚠️ QLever ping failed. Relying strictly on ES Summary.")

        # --- STEP 4: THE COMBO PAYLOAD ---
        payload = {
            "entity_matched": entity_title,
            "semantic_summary": summary_text, 
            "verified_graph_facts": clean_edges[:20] 
        }
        
        return json.dumps(payload, ensure_ascii=False)

# Make sure this matches how agent.py imports it!
kg_tool = GraphRAGWikipediaTool()