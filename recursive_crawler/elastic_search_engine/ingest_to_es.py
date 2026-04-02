import json
import re
from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm
import numpy as np
import tritonclient.http as httpclient
from transformers import AutoTokenizer
import os

# 1. Connect to Triton on Port 7000 (The port we just updated)
TRITON_URL = "localhost:7000"
try:
    triton_client = httpclient.InferenceServerClient(url=TRITON_URL)
    if triton_client.is_server_ready():
        print(f"[+] Connected to Triton Server at {TRITON_URL}")
except Exception as e:
    print(f"[!] Triton Connection Error: {e}")

# 2. Load the Tokenizer locally (Takes almost zero memory)
print("[*] Loading Gemma Tokenizer...")
tokenizer = AutoTokenizer.from_pretrained("google/embeddinggemma-300m")

def get_embeddings_from_triton(texts, batch_size=128):
    """Tokenizes text, sends it to Triton in safe batches, and returns the vectors."""
    all_embeddings = []
    
    # Process in strict batches to respect Triton's max_batch_size: 8
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]
        
        # Tokenize the text into integers
        encoded = tokenizer(
            batch_texts, 
            padding=True, 
            truncation=True, 
            max_length=512, # Max context length for ONNX
            return_tensors="np"
        )
        
        input_ids = encoded["input_ids"].astype(np.int64)
        attention_mask = encoded["attention_mask"].astype(np.int64)
        
        # Prepare Triton Inputs
        inputs = [
            httpclient.InferInput("input_ids", input_ids.shape, "INT64"),
            httpclient.InferInput("attention_mask", attention_mask.shape, "INT64")
        ]
        inputs[0].set_data_from_numpy(input_ids)
        inputs[1].set_data_from_numpy(attention_mask)
        
        # We only want the sentence_embedding array back
        outputs = [httpclient.InferRequestedOutput("sentence_embedding")]
        
        # Call the server
        response = triton_client.infer(model_name="gemma_embedding", inputs=inputs, outputs=outputs)
        batch_embeddings = response.as_numpy("sentence_embedding")
        
        all_embeddings.extend(batch_embeddings.tolist())
        
    return all_embeddings

# ---------------- CONFIGURATION ---------------- #
ES_HOST = "http://localhost:9200"
INDEX_NAME = "bd_gov_chunks"
TREE_PATH = "../PageIndex/results/bd_gov_ecosystem_structure.json" 
EMBEDDING_MODEL = "google/embeddinggemma-300m"
CHUNK_SIZE = 1500  # Characters per chunk
CHUNK_OVERLAP = 200 # Overlap to prevent cutting context in half
BATCH_SIZE = 250   # How many chunks to embed and upload at once
# ----------------------------------------------- #

# Connect to ES
es = Elasticsearch(ES_HOST)
# --- SAFETY LOCK ---
if es.indices.exists(index=INDEX_NAME):
    doc_count = es.count(index=INDEX_NAME)['count']
    if doc_count > 0:
        print(f"\n[WARNING] The database '{INDEX_NAME}' already contains {doc_count} chunks!")
        confirm = input("Are you sure you want to re-ingest all data? (y/N): ")
        if confirm.lower() != 'y':
            print("[*] Aborting safely. Your data was not touched.")
            exit()

def flatten_tree(nodes_list):
    flat_list = []
    for node in nodes_list:
        flat_list.append(node)
        if 'nodes' in node and isinstance(node['nodes'], list):
            flat_list.extend(flatten_tree(node['nodes']))
    return flat_list

def chunk_text(text, chunk_size, overlap):
    """Splits text into overlapping chunks, ensuring we don't slice words in half."""
    words = text.split()
    chunks = []
    current_chunk = []
    current_len = 0
    
    for word in words:
        current_chunk.append(word)
        current_len += len(word) + 1 # +1 for the space
        
        if current_len >= chunk_size:
            chunks.append(" ".join(current_chunk))
            # Keep the overlap amount from the end of the current chunk
            overlap_words = []
            overlap_len = 0
            for w in reversed(current_chunk):
                overlap_words.insert(0, w)
                overlap_len += len(w) + 1
                if overlap_len >= overlap:
                    break
            current_chunk = overlap_words
            current_len = overlap_len
            
    if current_chunk and len(" ".join(current_chunk)) > 50: # Ignore tiny leftover chunks
        chunks.append(" ".join(current_chunk))
        
    return chunks

def process_and_ingest():
    print(f"[*] Loading Local Embedding Model: {EMBEDDING_MODEL}...")

    print("[*] Loading and Flattening Official PageIndex Tree...")
    with open(TREE_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
        
    root_nodes = raw_data.get('structure', raw_data.get('nodes', [])) if isinstance(raw_data, dict) else raw_data
    all_nodes = flatten_tree(root_nodes)

    print("[*] Chunking documents and inheriting metadata...")
    all_chunks = []
    
    for n in all_nodes:
        text = n.get('text', '')
        if not text:
            continue
            
        # Extract the metadata safely
        summary = ""
        if "**সারসংক্ষেপ (Summary):**" in text:
            summary_parts = text.split("**সারসংক্ষেপ (Summary):**")[1].split("**কিওয়ার্ড")
            if len(summary_parts) > 0:
                summary = summary_parts[0].strip()
                
        site_title = n.get('title', n.get('heading', 'Unknown'))
        node_id = n.get('node_id', 'unknown_id')
        url = n.get('url', f"https://{node_id}.gov.bd") # Fallback if URL isn't in JSON
        
        # Chop the raw text
        text_chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        
        for i, chunk in enumerate(text_chunks):
            # E5 models perform best when indexing documents with the "passage: " prefix
            passage_text = passage_text = f"title: none | text: {site_title} - {chunk}"
            
            all_chunks.append({
                "chunk_id": f"{node_id}_part_{i}",
                "node_id": node_id,
                "url": url,
                "site_title": site_title,
                "site_summary": summary[:250],
                "chunk_text": chunk,
                "passage_for_embedding": passage_text
            })

    print(f"[+] Created {len(all_chunks)} total chunks from {len(all_nodes)} nodes.")
    print("[*] Embedding and Bulk Uploading to Elasticsearch (grab a coffee)...")

    # Process in batches
    CHECKPOINT_FILE = "ingestion_progress.txt"
    start_index = 0

    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            saved_index = f.read().strip()
            if saved_index.isdigit():
                start_index = int(saved_index)
                print(f"[*] Resuming from saved checkpoint: Chunk #{start_index}...")

    # Process in batches (skipping already completed chunks)
    # We update the tqdm progress bar to reflect the resume state
    for i in tqdm(
        range(start_index, len(all_chunks), BATCH_SIZE), 
        initial=start_index // BATCH_SIZE, 
        total=len(all_chunks) // BATCH_SIZE
    ):
        batch = all_chunks[i:i + BATCH_SIZE]
        texts_to_embed = [item["passage_for_embedding"] for item in batch]
        
        # Generate vectors via Triton
        embeddings = get_embeddings_from_triton(texts_to_embed)
        
        # Prepare Elasticsearch bulk actions
        actions = []
        for j, item in enumerate(batch):
            doc = {
                "_index": INDEX_NAME,
                "_id": item["chunk_id"], # Prevents duplicates
                "_source": {
                    "chunk_id": item["chunk_id"],
                    "node_id": item["node_id"],
                    "url": item["url"],
                    "site_title": item["site_title"],
                    "site_summary": item["site_summary"],
                    "chunk_text": item["chunk_text"],
                    "chunk_vector": embeddings[j] # Already a list!
                }
            }
            actions.append(doc)
            
        # Fire them into the database and save progress
        try:
            helpers.bulk(es, actions)
            
            # Save the next starting index to the hard drive
            with open(CHECKPOINT_FILE, "w") as f:
                f.write(str(i + BATCH_SIZE))
                
        except Exception as e:
            print(f"\n[!] Bulk upload error on batch {i}: {e}")
            # If it fails here, the progress file won't update, so it will naturally retry this batch next time

    print("[+] Enterprise Data Ingestion Complete!")
    
    # Clean up the checkpoint file when 100% finished
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
if __name__ == "__main__":
    process_and_ingest()