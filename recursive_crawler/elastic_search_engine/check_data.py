from elasticsearch import Elasticsearch

# Connect to your local database
es = Elasticsearch("http://localhost:9200")
INDEX_NAME = "bd_gov_chunks"

# We are doing a pure Lexical (Keyword) search with strict rules
# We are doing a Lexical (Keyword) search handling Bengali spelling variations
# Lexical search for Freedom Fighter Certificate/Gazette Name Correction
# Lexical search for Guardianship vs Adoption
# Lexical search for District Level NICU/SCANU facilities
search_query = {
    "query": {
        "bool": {
            "must": [
                # The chunk MUST contain at least one of these exact medical terms
                {
                    "bool": {
                        "should": [
                            {"match": {"chunk_text": "এনআইসিইউ"}},
                            {"match": {"chunk_text": "NICU"}},
                            {"match": {"chunk_text": "স্ক্যানো"}},      # SCANU
                            {"match": {"chunk_text": "SCANU"}},
                            {"match_phrase": {"chunk_text": "নিবিড় পরিচর্যা"}} # Intensive Care
                        ],
                        "minimum_should_match": 1
                    }
                }
            ],
            "should": [
                # Context words to pinpoint "District Level Hospitals for Children"
                {"match": {"chunk_text": "জেলা"}},         # District
                {"match": {"chunk_text": "সদর"}},         # Sadar (District hospitals are usually 'Sadar Hospitals')
                {"match": {"chunk_text": "হাসপাতাল"}},    # Hospital
                {"match": {"chunk_text": "শিশু"}},         # Child
                {"match": {"chunk_text": "নবজাতক"}}       # Newborn
            ],
            "minimum_should_match": 2 # Must match at least 2 context words
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