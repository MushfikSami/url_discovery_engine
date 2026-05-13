import requests

QLEVER_URL = "http://localhost:7005"

# SPARQL query to grab 100 distinct entities (Subjects) from your graph
# P106 is "occupation", Q82955 is "politician"
sparql_query = """
SELECT DISTINCT ?subject WHERE { 
  ?subject <http://www.wikidata.org/prop/direct/P106> <http://www.wikidata.org/entity/Q82955> .
  FILTER(STRSTARTS(STR(?subject), "http://www.wikidata.org/entity/Q"))
} 
LIMIT 20
"""

print("📡 Fetching Q-IDs from local QLever database...\n")

try:
    response = requests.get(
        QLEVER_URL, 
        params={"query": sparql_query}, 
        headers={"Accept": "application/sparql-results+json"},
        timeout=5.0
    )
    
    if response.status_code == 200:
        results = response.json()['results']['bindings']
        q_ids = []
        
        for row in results:
            # Extract just the "Q12345" part from the full URL
            raw_url = row['subject']['value']
            q_id = raw_url.split('/')[-1]
            q_ids.append(q_id)
            
        # Print them out in a clean, comma-separated list
        print(", ".join(q_ids))
        print(f"\n✅ Successfully pulled {len(q_ids)} Q-IDs.")
    else:
        print(f"❌ Error: QLever returned status code {response.status_code}")
        
except Exception as e:
    print(f"⚠️ Connection failed: {e}")