import sys
import requests
import pandas as pd
import difflib
import time

# --- Configuration ---
CSV_PATH = "./data/bangladesh_bn_wiki_true_massive.csv" # Assumes you run this from the 'agent' folder
QLEVER_URL = "http://localhost:7005"

def verify_entity(search_term: str):
    print(f"\n🔍 Searching for: '{search_term}'...")
    
    # --- PHASE 1: Check the CSV Index ---
    # --- PHASE 1: Check the CSV Index ---
    try:
        df = pd.read_csv(CSV_PATH)
        entity_index = dict(zip(df['Bangla_Wikipedia_Title'], df['Wikidata_ID']))
    except FileNotFoundError:
        print(f"❌ Error: Could not find CSV at {CSV_PATH}")
        return

    # 1. First, try an exact match
    if search_term in entity_index:
        exact_match = search_term
        print("✅ Exact Match Found!")
    else:
        # 2. If no exact match, try a STRICT fuzzy match (85% similarity instead of 60%)
        matches = difflib.get_close_matches(search_term, entity_index.keys(), n=1, cutoff=0.85)
        
        if not matches:
            print(f"❌ Result: '{search_term}' does NOT exist in your local Wikipedia index.")
            print("   (It might be located at Depth 3 or 4 of the Wikipedia category tree).")
            return
            
        exact_match = matches[0]
        print(f"⚠️ Exact match not found. Autocorrected to closest strict match: '{exact_match}'")
        
    q_id = entity_index[exact_match]
    
    # Construct the exact Bengali Wikipedia URL
    wiki_url = f"https://bn.wikipedia.org/wiki/{exact_match.replace(' ', '_')}"
    
    print("✅ Found in Index!")
    print(f"   Name:     {exact_match}")
    print(f"   Q-ID:     {q_id}")
    print(f"   Wikidata: https://www.wikidata.org/wiki/{q_id}")
    print(f"   Article:  {wiki_url}") # <--- Your new trace-back link!    
    # --- PHASE 2: Check the Local QLever Database ---
    print("\n⚡ Pinging local QLever database for facts...")
    
    # Query to count total facts and fetch a few examples
    query = f"""
    SELECT ?predicate ?object WHERE {{ 
      <http://www.wikidata.org/entity/{q_id}> ?predicate ?object 
    }}
    """
    
    start_time = time.time()
    try:
        response = requests.get(
            QLEVER_URL, 
            params={"query": query}, 
            headers={"Accept": "application/sparql-results+json"},
            timeout=2.0
        )
        
        if response.status_code == 200:
            results = response.json()['results']['bindings']
            elapsed = (time.time() - start_time) * 1000
            
            if not results:
                print(f"⚠️ Warning: Entity exists in CSV, but has 0 relational edges in QLever.")
            else:
                print(f"✅ Found {len(results)} facts in {elapsed:.2f} ms!")
                print("\n   --- Sample Facts ---")
                
                # Print up to 5 sample edges to verify data quality
                for i, row in enumerate(results[:5]):
                    p = row['predicate']['value'].split('/')[-1]
                    o = row['object']['value'].split('/')[-1]
                    print(f"   • {exact_match}  -->  {p}  -->  {o}")
                    
                if len(results) > 5:
                    print(f"   ... and {len(results) - 5} more.")
        else:
            print(f"❌ QLever Error: HTTP {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Could not connect to QLever on {QLEVER_URL}. Is the Docker container running?")

if __name__ == "__main__":
    # Allow running directly from terminal: python check_entity.py "ঢাকা"
    if len(sys.argv) > 1:
        term = " ".join(sys.argv[1:])
        verify_entity(term)
    else:
        # Or run it interactively
        while True:
            user_input = input("\nEnter Bengali entity name (or 'q' to quit): ")
            if user_input.lower() == 'q':
                break
            verify_entity(user_input)