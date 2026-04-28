from elasticsearch import Elasticsearch

# Connect to your local database
es = Elasticsearch("http://localhost:9200")
INDEX_NAME = "bd_gov_chunks"

# We are doing a pure Lexical (Keyword) search with strict rules
# We are doing a Lexical (Keyword) search handling Bengali spelling variations
# Lexical search for Freedom Fighter Certificate/Gazette Name Correction
# Lexical search for Guardianship vs Adoption
# Lexical search for District Level NICU/SCANU facilities
# Lexical search for Freedom Fighter Certificate/Gazette Name Correction
search_query = {
    "query": {
        "bool": {
            "must": [
                # The chunk MUST be related to Freedom Fighters
                {"match": {"chunk_text": "নাগরিকত্ব"}} 
            ],
            "should": [
                # Context words for name correction
                {"match": {"chunk_text": "সনদ"}}       # Name
                   # Form
            ],
            "minimum_should_match": 3 # Stricter matching: Must contain at least 3 of the context words to filter out generic lists of freedom fighters
        }
    },
    "size": 5, 
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