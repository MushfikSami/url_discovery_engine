from elasticsearch import Elasticsearch

# Connect to your local database
es = Elasticsearch("http://localhost:9200")
INDEX_NAME = "bd_gov_chunks"

# We are doing a pure Lexical (Keyword) search with strict rules
search_query = {
    "query": {
        "bool": {
            "must": [
                {"match": {"chunk_text": "কারিগরি"}} # MUST contain "Technical"
            ],
            "should": [
                {"match": {"chunk_text": "সনদপত্র"}},   # "Official Certificate"
                {"match": {"chunk_text": "সার্টিফিকেট"}}, # "Certificate" (English loan word)
                {"match": {"chunk_text": "হারানো"}},    # "Lost"
                {"match": {"chunk_text": "উত্তোলন"}}     # "Retrieval"
            ],
            "minimum_should_match": 2 # Must match at least two of the optional words
        }
    },
    "size": 5, # Give us the top 5 raw matches
    "_source": ["chunk_text", "url", "site_title"]
}

try:
    response = es.search(index=INDEX_NAME, body=search_query)
    hits = response["hits"]["hits"]
    total_found = response["hits"]["total"]["value"]
    
    print("="*50)
    print(f"DATABASE SCAN COMPLETE: Found {total_found} potential matches.")
    print("="*50 + "\n")
    
    for i, hit in enumerate(hits):
        source = hit["_source"]
        print(f"--- MATCH {i+1} ---")
        print(f"Score: {hit['_score']}")
        print(f"Site:  {source.get('site_title', 'Unknown')}")
        print(f"URL:   {source.get('url', 'No URL')}")
        
        # Print the first 500 characters of the text
        text = source.get('chunk_text', '')
        clean_text = text[:500].replace('\n', ' ')
        print(f"Text:  {clean_text}...\n")

except Exception as e:
    print(f"[!] Error connecting to Elasticsearch: {e}")