import json
from elasticsearch import Elasticsearch
from neo4j import GraphDatabase
import requests
from transformers import AutoTokenizer
import numpy as np
class GraphRAGWikipediaTool:
    def __init__(self, es_url="http://localhost:9200", neo4j_uri =  "bolt+ssc://localhost:7687", neo4j_user="neo4j", neo4j_pass="8QjEHYATrDaotYHm4v0MgZH9+0qzbCnGU+NzGB4DTQ0="):
        # 1. Initialize Elasticsearch
        self.index_name = "wikipedia_bn_graphrag"
        self.es = Elasticsearch(es_url)
        
        # 2. Initialize Neo4j Driver
        self.neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        self.triton_url = "http://localhost:7000/v2/models/gemma_embedding/infer"
        self.tokenizer = AutoTokenizer.from_pretrained("google/embeddinggemma-300m")
        print("🔗 Connected to Elasticsearch (Vector) and Neo4j (Graph).")

    def close(self):
        """Always good practice to close the Neo4j driver when shutting down."""
        self.neo4j_driver.close()

    def get_triton_embedding(self, text: str) -> list:
        """Tokenizes text and fetches embeddings from Triton."""
        TRITON_URL = "http://localhost:7000/v2/models/gemma_embedding/infer"
        
        # 1. Tokenize the text locally
        encoded = self.tokenizer(
            text, 
            padding=True, 
            truncation=True, 
            max_length=512, 
            return_tensors="np"
        )
        
        input_ids = encoded["input_ids"].astype(np.int64).tolist()
        attention_mask = encoded["attention_mask"].astype(np.int64).tolist()

        # 2. Build the precise ONNX payload Triton expects
        payload = {
            "inputs": [
                {
                    "name": "input_ids",
                    "shape": [len(input_ids), len(input_ids[0])],
                    "datatype": "INT64",
                    "data": input_ids
                },
                {
                    "name": "attention_mask",
                    "shape": [len(attention_mask), len(attention_mask[0])],
                    "datatype": "INT64",
                    "data": attention_mask
                }
            ]
        }
        
        # 3. Send to Triton and extract the 768-dim vector
        # 3. Send to Triton
        try:
            response = requests.post(TRITON_URL, json=payload, timeout=5.0)
            response.raise_for_status()
            
            outputs = response.json().get("outputs", [])
            for output in outputs:
                if output["name"] == "sentence_embedding":
                    data = output["data"]
                    
                    # Check if Triton flattened it (a simple list of 768 floats)
                    if len(data) == 768:
                        return data
                    # Check if it's nested (a list containing a list of 768 floats)
                    elif len(data) > 0 and isinstance(data[0], list):
                        return data[0]
                        
            return []
        except Exception as e:
            print(f"⚠️ Triton Embedding Error: {e}")
            return []
        
    def search_entity(self, user_query: str) -> str:
        print(f"\n[GraphRAG] 1. Initiating Search for: '{user_query}'")
        
        query_vector = self.get_triton_embedding(user_query)
        
        # ADD THIS DEBUG LINE:
        print(f"🐛 [DEBUG] Triton Vector Length: {len(query_vector)}")
        
        if not query_vector:
            return "RESULT_NOT_FOUND: Failed to generate embedding from Triton."
        # --- TRUE PARALLEL HYBRID SEARCH (ES 8.x) ---
        es_query = {
            "size": 1,
            "min_score": 0.5, # একটু কমিয়ে রাখুন যাতে সেফলি ডেটা পায়
            "knn": {
                "field": "text_vector",
                "query_vector": query_vector,
                "k": 10,
                "num_candidates": 100,
                "boost": 0.5  # ভেক্টরের পাওয়ার একটু কমানো হলো
            },
            "query": {
                "bool": {
                    "should": [
                        {
                            "match_phrase": { # এক্স্যাক্ট ফ্রেজ ম্যাচিং
                                "title": {
                                    "query": user_query,
                                    "boost": 5.0 # 👈 এক্স্যাক্ট টাইটেলকে বিশাল পাওয়ার দেওয়া হলো
                                }
                            }
                        },
                        {
                            "match": {
                                "title": {
                                    "query": user_query,
                                    "fuzziness": "AUTO",
                                    "boost": 1.0
                                }
                            }
                        }
                    ]
                }
            }
        }
        
        try:
            es_response = self.es.search(index=self.index_name, body=es_query)
            hits = es_response['hits']['hits']
            
            if not hits:
                print("❌ [GraphRAG] Miss! Entity not found or score too low.")
                return "RESULT_NOT_FOUND"
                
            best_match = hits[0]['_source']
            entity_title = best_match['title']
            q_id = best_match['q_id']
            summary_text = best_match['summary']
            
            print(f"[GraphRAG] 2. Found Context: {entity_title} ({q_id})")
            
        except Exception as e:
            return f"RESULT_NOT_FOUND: ES Error: {e}"

        # --- EXACT GRAPH RETRIEVAL (NEO4J) ---
        print(f"[GraphRAG] 3. Pinging Neo4j for Edges...")
        clean_edges = []
        
        # Define the Cypher Query
        # NOTE: Update 'qid' and 'label' if your Neo4j property names are different!
        cypher_query = """
        MATCH (subject {qid: $target_qid})-[rel]->(object)
        RETURN type(rel) AS predicate, object.label AS object_name, object.qid AS object_qid
        LIMIT 20
        """
        
        try:
            # Open a session and run the query
            with self.neo4j_driver.session() as session:
                result = session.run(cypher_query, target_qid=q_id)
                
                for record in result:
                    # Format it exactly how the LLM expects it based on your prompt
                    p_node = record["predicate"]
                    o_node = record["object_name"] or record["object_qid"] # Fallback to QID if label is missing
                    clean_edges.append({f"Predicate ({p_node})": o_node})
                    
        except Exception as e:
            print(f"⚠️ Neo4j ping failed: {e}. Relying strictly on ES Summary.")

        # --- THE COMBO PAYLOAD ---
        payload = {
            "entity_matched": entity_title,
            "semantic_summary": summary_text, 
            "verified_graph_facts": clean_edges 
        }
        
        return json.dumps(payload, ensure_ascii=False)

# Instantiated for agent.py (Update credentials here!)
kg_tool = GraphRAGWikipediaTool(neo4j_uri= "bolt+ssc://localhost:7687", neo4j_user="neo4j", neo4j_pass="8QjEHYATrDaotYHm4v0MgZH9+0qzbCnGU+NzGB4DTQ0=")