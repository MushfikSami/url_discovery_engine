import requests
import pandas as pd
import json
import difflib

class QLeverWikipediaTool:
    def __init__(self, csv_path="./data/bangladesh_bn_wiki_true_massive.csv", qlever_url="http://localhost:7005"):
        self.qlever_url = qlever_url
        
        # Load the CSV into an ultra-fast lookup dictionary in RAM
        print("⚙️ Loading Knowledge Graph Text-to-QID Index...")
        df = pd.read_csv(csv_path)
        # Create a dictionary of { "ঢাকা": "Q1354", ... }
        self.entity_index = dict(zip(df['Bangla_Wikipedia_Title'], df['Wikidata_ID']))
        print(f"✅ Indexed {len(self.entity_index)} entities for the Agent.")

    def search_entity(self, entity_name: str) -> str:
        """
        The actual function the LLM will call. 
        It takes a text name, finds the Q-ID, and queries the local graph.
        """
        print(f"\n[TOOL EXECUTION] LLM requested search for: '{entity_name}'")
        
        # 1. Fuzzy Matching (In case the LLM misspells the Bengali title)
        matches = difflib.get_close_matches(entity_name, self.entity_index.keys(), n=1, cutoff=0.6)
        
        if not matches:
            return json.dumps({"error": f"Entity '{entity_name}' not found in the local database."})
            
        exact_match = matches[0]
        q_id = self.entity_index[exact_match]
        print(f"[TOOL EXECUTION] Mapped '{entity_name}' -> '{exact_match}' ({q_id})")

        # 2. Hit the local QLever Database (Sub-500ms guaranteed)
        query = f"SELECT ?predicate ?object WHERE {{ <http://www.wikidata.org/entity/{q_id}> ?predicate ?object }}"
        
        try:
            response = requests.get(
                self.qlever_url, 
                params={"query": query}, 
                headers={"Accept": "application/sparql-results+json"},
                timeout=2.0
            )
            
            if response.status_code == 200:
                results = response.json()['results']['bindings']
                
                # Clean up the output so the LLM doesn't waste context window on long URIs
                clean_edges = []
                for row in results:
                    p = row['predicate']['value'].split('/')[-1]
                    o = row['object']['value'].split('/')[-1]
                    clean_edges.append({p: o})
                    
                return json.dumps({
                    "entity_found": exact_match,
                    "q_id": q_id,
                    "relational_edges": clean_edges
                })
            else:
                return json.dumps({"error": f"QLever DB Error: {response.status_code}"})
                
        except Exception as e:
            return json.dumps({"error": f"Database connection failed: {str(e)}"})

# For isolated testing:
if __name__ == "__main__":
    tool = QLeverWikipediaTool()
    print(tool.search_entity("ঢাকা"))