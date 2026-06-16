# search.py
import time
from config import INDEX_NAME

def execute_hybrid_search(es_client, text_query, location_filter=None, org_filter=None, top_k=5):
    print(f"\n[PHASE 2] Executing Hybrid Query...")
    print(f" 📝 Text Search : '{text_query}'")
    print(f" 🌐 Graph Filter: Location='{location_filter}', Organization='{org_filter}'")
    
    # 1. Build the Hybrid Query Structure
    query_body = {
        "query": {
            "bool": {
                # MUST: Perform standard Bengali full-text search
                "must": [
                    {"match": {"text_content": text_query}}
                ],
                # FILTER: Perform strict Graph Database entity checks (Zero latency cost)
                "filter": []
            }
        }
    }
    
    # 2. Dynamically attach the Graph rules if they were requested
    if location_filter:
        query_body["query"]["bool"]["filter"].append(
            {"term": {"graph.locations": location_filter}}
        )
    if org_filter:
        query_body["query"]["bool"]["filter"].append(
            {"term": {"graph.organizations": org_filter}}
        )

    # 3. Execute!
    start_time = time.time()
    response = es_client.search(index=INDEX_NAME, body=query_body, size=top_k)
    latency_ms = (time.time() - start_time) * 1000 
    
    hits = response['hits']['hits']
    total_found = response['hits']['total']['value']
    
    print(f"⚡ Hybrid Retrieval completed in: {latency_ms:.3f} milliseconds")
    print(f"📄 Found {total_found} matching documents.")
    
    return hits