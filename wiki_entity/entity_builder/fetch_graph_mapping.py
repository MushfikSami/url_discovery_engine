import requests
import pandas as pd
import time

def fetch_specific_relationships(q_id_list):
    print(f"🕸️ Connecting to Wikidata for {len(q_id_list)} specific entities...")
    
    # Format the Python list into SPARQL format (e.g., "wd:Q1354 wd:Q858")
    formatted_values = " ".join([f"wd:{q_id}" for q_id in q_id_list])
    
    url = 'https://query.wikidata.org/sparql'
    
    # --- The DIRECT INJECTION SPARQL Query ---
    query = f"""
    SELECT ?subject ?subjectLabel ?property ?propertyLabel ?object ?objectLabel WHERE {{
      
      # 1. INJECT THE EXACT IDs: No searching required, instant lookup
      VALUES ?subject {{ {formatted_values} }}
      
      # 2. Get all outgoing properties
      ?subject ?predicate ?object.
      
      # 3. CRITICAL OPTIMIZATION: Ensure it's a URL before checking if it's a Q-Entity
      FILTER(isIRI(?object))
      FILTER(STRSTARTS(STR(?object), "http://www.wikidata.org/entity/Q"))
      
      # 4. Get the Property Names
      ?property wikibase:directClaim ?predicate.
      
      # 5. Fetch labels in Bengali/English
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "bn,en". }}
    }}
    """
    
    headers = {
        'User-Agent': 'BDEntityMapperBot/2.0 (explicit_batch_mode)',
        'Accept': 'application/sparql-results+json'
    }
    
    start_time = time.time()
    
    try:
        response = requests.get(url, headers=headers, params={'query': query}, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return []
            
        data = response.json()
        results = data['results']['bindings']
        
        print(f"⚡ Graph Mapping completed in {time.time() - start_time:.2f} seconds.")
        print(f"🔗 Extracted {len(results)} Entity-to-Entity relationships.")
        
        # Parse the Triples
        graph_data = []
        for row in results:
            graph_data.append({
                "Subject_ID": row['subject']['value'].split('/')[-1],
                "Subject_Name": row['subjectLabel']['value'],
                "Relationship_ID": row['property']['value'].split('/')[-1],
                "Relationship_Name": row['propertyLabel']['value'],
                "Object_ID": row['object']['value'].split('/')[-1],
                "Object_Name": row['objectLabel']['value']
            })
            
        return graph_data
        
    except requests.exceptions.Timeout:
        print("❌ The request timed out.")
        return []

if __name__ == "__main__":
    # 1. Read your newly generated MASSIVE list of entities
    df = pd.read_csv("bangladesh_bn_wiki_true_massive.csv")
    all_q_ids = df['Wikidata_ID'].tolist()
    
    print(f"Total entities to map: {len(all_q_ids)}")
    
    all_edges = []
    chunk_size = 50 # Process 50 at a time to prevent server timeouts
    
    # 2. Loop through them in chunks
    for i in range(0, len(all_q_ids), chunk_size):
        chunk = all_q_ids[i:i + chunk_size]
        print(f"\nProcessing chunk {i} to {i + len(chunk)}...")
        
        edges = fetch_specific_relationships(chunk)
        all_edges.extend(edges)
        
        # 3. BE POLITE: Sleep for 1 second so Wikidata doesn't ban your IP
        time.sleep(1)
        
    # 4. Save the final massive graph
    if all_edges:
        edges_df = pd.DataFrame(all_edges)
        edges_df.to_csv("wikidata_massive_relational_map.csv", index=False, encoding='utf-8-sig')
        print(f"\n✅ DONE! Saved {len(edges_df)} total edges to CSV.")