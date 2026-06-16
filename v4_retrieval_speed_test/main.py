# main.py
import sys
import pandas as pd
from config import DATASET_PATH, INDEX_NAME
from database import get_es_client
from indexer import setup_hybrid_index, bulk_ingest_csv
from search import execute_hybrid_search

def run_benchmark():
    try:
        es = get_es_client()
        force_reset = "--reset" in sys.argv
        
        if force_reset or not es.indices.exists(index=INDEX_NAME):
            print("🏗️ Starting Hybrid AI Ingestion phase...")
            df = pd.read_csv(DATASET_PATH)
            setup_hybrid_index(es)
            bulk_ingest_csv(es, df)
        else:
            print("⏩ Hybrid Index found. Skipping ingestion.")
        
        print("-" * 50)
        
        # --- THE QLEVER-STYLE HYBRID QUERY ---
        # Text Goal: Find paragraphs about allowance applications
        TEXT_TO_FIND = "আবেদন করার নিয়ম" 
        
        # Graph Fact 1: Only return it if the organization is the Ministry of Social Welfare
        ORGANIZATION_FACT = "সমাজকল্যাণ মন্ত্রণালয়" 
        
        results = execute_hybrid_search(
            es_client=es, 
            text_query=TEXT_TO_FIND, 
            org_filter=ORGANIZATION_FACT, # Set to None if you don't want to filter
            location_filter=None 
        )
        
        if results:
            print(f"\n--- Top Hits ---")
            for i, hit in enumerate(results, start=1):
                graph = hit['_source']['graph']
                print(f"\n[{i}] Score: {hit['_score']}")
                print(f"  🏛️ Graph Entities:")
                print(f"     - Organizations: {graph.get('organizations', [])}")
                print(f"     - Locations: {graph.get('locations', [])}")
                print(f"     - Services: {graph.get('services', [])}")
        else:
            print("\n❌ No documents matched the hybrid criteria.")
            
    except Exception as e:
        print(f"\n❌ A critical error occurred: {e}")

if __name__ == "__main__":
    run_benchmark()