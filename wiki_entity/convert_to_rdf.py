import pandas as pd
import time

print("🔄 Converting CSV to N-Triples...")
start = time.time()

df = pd.read_csv("wikidata_massive_relational_map.csv")
output_file = "bd_graph.nt"

with open(output_file, 'w', encoding='utf-8') as f:
    for index, row in df.iterrows():
        # Format as standard RDF URLs
        sub = f"<http://www.wikidata.org/entity/{row['Subject_ID']}>"
        pred = f"<http://www.wikidata.org/entity/{row['Relationship_ID']}>"
        obj = f"<http://www.wikidata.org/entity/{row['Object_ID']}>"
        
        # Write the triple (Subject Predicate Object .)
        f.write(f"{sub} {pred} {obj} .\n")

print(f"✅ Conversion complete in {time.time() - start:.2f} seconds.")
print(f"💾 File saved as: {output_file}")