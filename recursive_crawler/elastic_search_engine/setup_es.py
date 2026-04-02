from elasticsearch import Elasticsearch

# Connect to your local Elasticsearch instance
es = Elasticsearch("http://localhost:9200")

INDEX_NAME = "bd_gov_chunks"

# The Blueprint (Notice we removed the outer "mappings" wrapper for 8.x syntax)
mapping = {
    "properties": {
        "chunk_id": {"type": "keyword"},
        "node_id": {"type": "keyword"},
        "url": {"type": "keyword"},
        "site_title": {"type": "text", "analyzer": "bengali"},
        "site_summary": {"type": "text", "analyzer": "bengali"},
        "chunk_text": {"type": "text", "analyzer": "bengali"},
        "chunk_vector": {
            "type": "dense_vector",
            "dims": 768,
            "index": True,
            "similarity": "cosine"
        }
    }
}

def create_index():
    print(f"[*] Cleaning up old '{INDEX_NAME}' index (if it exists)...")
    # This safely deletes the index if it exists, and ignores the error if it doesn't.
    # Completely bypasses the HTTP HEAD request bug!
    es.indices.delete(index=INDEX_NAME, ignore_unavailable=True)
        
    print(f"[*] Creating new '{INDEX_NAME}' index with Hybrid mapping...")
    # ES 8.x syntax uses explicit keyword arguments
    es.indices.create(index=INDEX_NAME, mappings=mapping)
    print("[+] Index created successfully! ES is ready for data.")

if __name__ == "__main__":
    create_index()