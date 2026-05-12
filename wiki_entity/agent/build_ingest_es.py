import bz2
import xml.etree.ElementTree as ET
import pandas as pd
import mwparserfromhell
from elasticsearch import Elasticsearch, helpers
import requests
import time
from transformers import AutoTokenizer
import numpy as np 
import json 
from elasticsearch.helpers import BulkIndexError

# Initialize the tokenizer (use the exact model repo you used to generate the ONNX file)
# If it is Gemma, it might be "google/gemma-2b" or the specific embedding model repo.
tokenizer = AutoTokenizer.from_pretrained("google/embeddinggemma-300m") # Update if your tokenizer is different


# --- Configuration ---
XML_DUMP_PATH = "./data/bnwiki-latest-pages-articles.xml.bz2"
CSV_PATH = "./data/bangladesh_bn_wiki_true_massive.csv"
ES_URL = "http://localhost:9200"
INDEX_NAME = "wikipedia_bn_graphrag"

# --- Triton Configuration ---
TRITON_URL = "http://localhost:7000/v2/models/gemma_embedding/infer" # Update 'embgemma' to your exact model name
EMBEDDING_DIMS = 768 # UPDATE THIS: Gemma 2B=2048, Gemma 7B=3072, etc.

es = Elasticsearch(ES_URL)

def get_triton_embedding(text: str) -> list:
    """Tokenizes text and fetches embeddings from Triton."""
    TRITON_URL = "http://localhost:7000/v2/models/gemma_embedding/infer"
    
    # 1. Tokenize the text locally
    encoded = tokenizer(
        text, 
        padding=True, 
        truncation=True, 
        max_length=512, 
        return_tensors="np"
    )
    
    input_ids = encoded["input_ids"].astype(np.int64).tolist()
    attention_mask = encoded["attention_mask"].astype(np.int64).tolist()

    # 2. Build the precise ONNX payload Triton expects
    payload = {
        "inputs": [
            {
                "name": "input_ids",
                "shape": [len(input_ids), len(input_ids[0])],
                "datatype": "INT64",
                "data": input_ids
            },
            {
                "name": "attention_mask",
                "shape": [len(attention_mask), len(attention_mask[0])],
                "datatype": "INT64",
                "data": attention_mask
            }
        ]
    }
    
    # 3. Send to Triton and extract the 768-dim vector
    # 3. Send to Triton
    try:
        response = requests.post(TRITON_URL, json=payload, timeout=5.0)
        response.raise_for_status()
        
        outputs = response.json().get("outputs", [])
        for output in outputs:
            if output["name"] == "sentence_embedding":
                data = output["data"]
                
                # Check if Triton flattened it (a simple list of 768 floats)
                if len(data) == 768:
                    return data
                # Check if it's nested (a list containing a list of 768 floats)
                elif len(data) > 0 and isinstance(data[0], list):
                    return data[0]
                    
        return []
    except Exception as e:
        print(f"⚠️ Triton Embedding Error: {e}")
        return []
    
def create_index():
    mapping = {
        "settings": {
            "analysis": {"analyzer": {"bengali_native": {"type": "bengali"}}}
        },
        "mappings": {
            "properties": {
                "title": {"type": "text", "analyzer": "bengali_native"},
                "summary": {"type": "text", "analyzer": "bengali_native"},
                "q_id": {"type": "keyword"},
                "text_vector": {
                    "type": "dense_vector",
                    "dims": EMBEDDING_DIMS, 
                    "index": True,
                    "similarity": "cosine"
                }
            }
        }
    }
    if es.indices.exists(index=INDEX_NAME):
        es.indices.delete(index=INDEX_NAME)
    es.indices.create(index=INDEX_NAME, body=mapping)
    print(f"✅ Created Elasticsearch Index: {INDEX_NAME} with {EMBEDDING_DIMS} dimensions.")

def extract_summary(wikitext):
    try:
        parsed = mwparserfromhell.parse(wikitext)
        clean_text = parsed.strip_code()
        return clean_text[:500].replace('\n', ' ').strip() + "..."
    except:
        return ""

def process_dump():
    print("⚙️ Loading CSV Entity Map...")
    df = pd.read_csv(CSV_PATH)
    valid_entities = dict(zip(df['Bangla_Wikipedia_Title'], df['Wikidata_ID']))
    
    print(f"🚀 Starting XML Parsing. Target Entities: {len(valid_entities)}")
    
    actions = []
    ns = "{http://www.mediawiki.org/xml/export-0.11/}" 
    
    start_time = time.time()
    count = 0
    
    with bz2.open(XML_DUMP_PATH, "rt", encoding="utf-8") as file:
        context = ET.iterparse(file, events=("end",))
        for event, elem in context:
            if elem.tag == f"{ns}page":
                title_elem = elem.find(f"{ns}title")
                revision = elem.find(f"{ns}revision")
                
                if title_elem is not None and revision is not None:
                    title = title_elem.text
                    
                    if title in valid_entities:
                        text_elem = revision.find(f"{ns}text")
                        if text_elem is not None and text_elem.text:
                            summary = extract_summary(text_elem.text)
                            
                            if summary:
                                vector_text = f"{title}. {summary}"
                                
                                # Call your local Triton Server!
                                embedding = get_triton_embedding(vector_text)
                                
                                if embedding:
                                    doc = {
                                        "_index": INDEX_NAME,
                                        "_source": {
                                            "title": title,
                                            "summary": summary,
                                            "q_id": valid_entities[title],
                                            "text_vector": embedding
                                        }
                                    }
                                    actions.append(doc)
                                    count += 1
                                    
                                    if len(actions) >= 100:
                                        try:
                                            helpers.bulk(es, actions)
                                            print(f"   ... Indexed {count} valid entities...")
                                        except BulkIndexError as e:
                                            print(f"\n🚨 ELASTICSEARCH REJECTED THE BATCH!")
                                            print(f"Reason for the first failed document:")
                                            print(json.dumps(e.errors[0], indent=2))
                                            import sys; sys.exit(1) # Stop the script so you can read the error
                                            
                                        actions = []
                elem.clear()
    
    if actions:
        helpers.bulk(es, actions)
        
    print(f"✅ Ingestion Complete! Indexed {count} articles in {(time.time()-start_time)/60:.2f} mins.")

if __name__ == "__main__":
    create_index()
    process_dump()