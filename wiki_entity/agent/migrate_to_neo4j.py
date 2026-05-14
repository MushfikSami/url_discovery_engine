import pandas as pd
import requests
from neo4j import GraphDatabase
import re

# --- Configuration ---
CSV_PATH = "./data/bangladesh_bn_wiki_true_massive.csv" # Ensure this path is correct!
QLEVER_URL = "http://localhost:7005"
NEO4J_URI = "bolt+ssc://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "8QjEHYATrDaotYHm4v0MgZH9+0qzbCnGU+NzGB4DTQ0=" # Update to your Neo4j password!

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

def clean_q_uri(uri_string):
    """Extracts just the Q-ID from a full Wikidata URL."""
    match = re.search(r'(Q\d+)$', uri_string)
    return match.group(1) if match else None

def extract_p_node(uri_string):
    """Extracts the P-Node (e.g., P31) regardless of the base URL."""
    match = re.search(r'(P\d+)$', uri_string)
    return match.group(1) if match else None

def migrate_graph():
    print("⚙️ Loading CSV Entity Map...")
    df = pd.read_csv(CSV_PATH)
    
    entity_map = dict(zip(df['Wikidata_ID'], df['Bangla_Wikipedia_Title']))
    target_qids = list(entity_map.keys())
    
    print(f"🚀 Found {len(target_qids)} valid entities. Starting extraction...")

    total_edges_inserted = 0
    skipped_predicates = set()

    with driver.session() as session:
        for i, q_id in enumerate(target_qids):
            sparql_query = f"""
            SELECT ?predicate ?object WHERE {{ 
              <http://www.wikidata.org/entity/{q_id}> ?predicate ?object .
            }} LIMIT 100
            """
            
            try:
                response = requests.get(
                    QLEVER_URL, 
                    params={"query": sparql_query}, 
                    headers={"Accept": "application/sparql-results+json"},
                    timeout=2.0
                )
                
                if response.status_code == 200:
                    results = response.json().get('results', {}).get('bindings', [])
                    
                    if not results:
                        continue
                        
                    subject_label = entity_map.get(q_id, q_id)
                    
                    for row in results:
                        p_uri = row['predicate']['value']
                        o_value = row['object']['value']
                        
                        predicate = extract_p_node(p_uri)
                        
                        # If it doesn't end in P + numbers, it's not a valid Wikidata property for our graph
                        if not predicate:
                            skipped_predicates.add(p_uri)
                            continue
                            
                        # Determine if object is another Entity or a Literal Text/Date
                        if row['object']['type'] == 'uri':
                            object_id = clean_q_uri(o_value)
                            if not object_id:
                                # Sometimes URLs point to external sites, not Q-nodes. Treat as string.
                                object_id = str(hash(o_value))
                                object_label = o_value
                            else:
                                object_label = entity_map.get(object_id, object_id) 
                        else:
                            object_id = str(hash(o_value)) 
                            object_label = o_value
                            
                        cypher_query = f"""
                        MERGE (s:Entity {{qid: $s_qid}})
                        ON CREATE SET s.label = $s_label
                        
                        MERGE (o:Entity {{qid: $o_qid}})
                        ON CREATE SET o.label = $o_label
                        
                        MERGE (s)-[:{predicate}]->(o)
                        """
                        
                        session.run(
                            cypher_query, 
                            s_qid=q_id, s_label=subject_label,
                            o_qid=object_id, o_label=object_label
                        )
                        total_edges_inserted += 1
                        
            except Exception as e:
                print(f"⚠️ Failed to process {q_id}: {e}")
                
            if (i + 1) % 100 == 0:
                print(f"   ... Processed {i + 1}/{len(target_qids)} entities. Edges inserted: {total_edges_inserted}")

    print(f"\n✅ Migration Complete! Successfully migrated {total_edges_inserted} facts into Neo4j.")
    
    if skipped_predicates:
        print("\n[Diagnostic] The following metadata predicate formats were safely ignored:")
        print(list(skipped_predicates)[:5]) # Print a sample to ensure we didn't miss good data

if __name__ == "__main__":
    try:
        migrate_graph()
    finally:
        driver.close()