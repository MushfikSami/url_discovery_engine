# indexer.py
import time
import pandas as pd
from elasticsearch import helpers
from config import INDEX_NAME
from llm_extractor import extract_structured_entities

def setup_hybrid_index(es_client):
    if es_client.indices.exists(index=INDEX_NAME):
        print("🗑️ Wiping old index...")
        es_client.indices.delete(index=INDEX_NAME)

    mapping = {
        "properties": {
            # 1. The Text Engine (For searching words)
            "text_content": {
                "type": "text",
                "analyzer": "bengali"
            },
            # 2. The Graph Engine (For filtering facts)
            "graph": {
                "properties": {
                    "locations": {"type": "keyword"},
                    "organizations": {"type": "keyword"},
                    "services": {"type": "keyword"}
                }
            },
            "original_row_id": {"type": "keyword"},
            "raw_data": {"type": "object", "enabled": False}
        }
    }
    es_client.indices.create(index=INDEX_NAME, mappings=mapping)
    print("✅ Created new Hybrid Text+Graph Index.")

def bulk_ingest_csv(es_client, dataframe):
    print(f"\n[PHASE 1] Building Knowledge Graph & Indexing {len(dataframe)} rows...")
    start_time = time.time()
    dataframe = dataframe.fillna("")
    
    def generate_actions():
        for index, row in dataframe.iterrows():
            text_content = " ".join([str(val) for val in row.values if val != ""])
            
            # Extract Structured Graph Data via vLLM
            graph_data = extract_structured_entities(text_content)
            
            if index > 0 and index % 50 == 0:
                print(f"   ... Processed {index}/{len(dataframe)} rows")

            yield {
                "_index": INDEX_NAME,
                "_source": {
                    "original_row_id": str(index),
                    "text_content": text_content, 
                    "graph": graph_data, # Inject the factual graph structure
                    "raw_data": row.to_dict() 
                }
            }
            
    helpers.bulk(es_client, generate_actions())
    es_client.indices.refresh(index=INDEX_NAME)
    print(f"📦 Successfully built Hybrid Index in {time.time() - start_time:.2f} seconds.")