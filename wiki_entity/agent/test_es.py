from elasticsearch import Elasticsearch
from build_ingest_es import get_triton_embedding

# Use the exact index name printed in your terminal
INDEX_NAME = "wikipedia_bn_graphrag" 
es = Elasticsearch("http://localhost:9200")

def manual_check():
    print("⚡ Connecting to Elasticsearch...")
    
    # 1. Verify Total Count
    es.indices.refresh(index=INDEX_NAME)
    count = es.count(index=INDEX_NAME)['count']
    print(f"✅ Total documents indexed: {count}\n")
    
    # 2. Run a Hybrid Test Query
    # Let's test with a typo to prove the hybrid engine works
    test_query = "বাংলাদেশের প্রধানমন্ত্রী কে?"  
    print(f"🔍 Testing Hybrid Search for: '{test_query}'")
    
    # Generate vector using your modular engine
    query_vector = get_triton_embedding(test_query)
    
    if not query_vector:
        print("❌ Failed to contact Triton for test embedding.")
        return
        
    print(f"✅ Generated {len(query_vector)}-dimensional query vector.")

    # 3. Execute the GraphRAG query
    # 3. Execute TRUE Parallel Hybrid Search (ES 8.x)
    es_query = {
        "size": 3, # Pull top 3 to see the ranking logic
        "knn": {
            "field": "text_vector",
            "query_vector": query_vector,
            "k": 10,
            "num_candidates": 100,
            "boost": 0.8 # Give semantic meaning slightly more weight than typos
        },
        "query": {
            "match": {
                "title": {
                    "query": test_query,
                    "fuzziness": "AUTO",
                    "boost": 0.2 # Lexical keyword matching acts as a secondary booster
                }
            }
        }
    }

    response = es.search(index=INDEX_NAME, body=es_query)
    hits = response['hits']['hits']

    if hits:
        print("\n🎯 TOP 3 MATCHES FOUND:")
        for i, hit in enumerate(hits):
            source = hit['_source']
            print(f"\n   --- Rank {i+1} ---")
            print(f"   Title:    {source.get('title')}")
            print(f"   Q-ID:     {source.get('q_id')}")
            print(f"   ES Score: {hit['_score']:.4f}")
    else:
        print("❌ Database returned no results.")
if __name__ == "__main__":
    manual_check()