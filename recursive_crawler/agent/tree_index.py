# tree_index.py
import json
from rank_bm25 import BM25Okapi
# --- Replace your current local imports with this ---
try:
    from agent.config import TREE_PATH
    from agent.utils import flatten_tree, tokenize, chunk_text
except ModuleNotFoundError:
    from config import TREE_PATH
    from utils import flatten_tree, tokenize, chunk_text
# ----------------------------------------------------
all_nodes = []
toc = []
bm25 = None

try:
    print("[*] Loading and Flattening Official PageIndex Tree...")
    with open(TREE_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
        
    if isinstance(raw_data, dict):
        root_nodes = raw_data.get('structure', raw_data.get('nodes', []))
    else:
        root_nodes = raw_data

    all_nodes = flatten_tree(root_nodes)

    for n in all_nodes:
        text = n.get('text', '')
        summary = ""
        if "**সারসংক্ষেপ (Summary):**" in text:
            summary = text.split("**সারসংক্ষেপ (Summary):**")[1].split("**কিওয়ার্ড")[0].strip()
            
        toc.append({
            "node_id": n.get('node_id', ''), 
            "title": n.get('title', n.get('heading', 'Unknown')), 
            "summary": summary[:250] 
        })

    toc = [n for n in toc if n["summary"]]
    print(f"[+] Successfully flattened {len(all_nodes)} total nodes.")
    
    print("[*] Building BM25 Search Index for all nodes (CPU Only)...")
    corpus = [tokenize(n['title'] + " " + n['summary']) for n in toc]
    bm25 = BM25Okapi(corpus)
    print("[+] BM25 Lexical Index Ready! VRAM preserved.")

except Exception as e:
    print(f"[!] Warning: Could not load tree structure. Error: {e}")

def execute_tree_search(query):
    """The tool called by the LLM. Uses BM25 to find top nodes and dynamically chunks the text."""
    if not bm25 or not toc:
        return "Database not loaded properly."

    tokenized_query = tokenize(query)
    
    # 1. Broad Node Retrieval (Top 5)
    top_nodes = bm25.get_top_n(tokenized_query, toc, n=5)
    if not top_nodes:
        return "No relevant documents found in the local tree index."

    selected_ids = [n['node_id'] for n in top_nodes]
    
    # 2. Extract Full Text
    raw_full_texts = []
    for node in all_nodes:
        if str(node.get('node_id', '')) in selected_ids:
            raw_full_texts.append(f"Source: {node.get('title', 'Unknown')}\n{node.get('text', '')}")
            
    combined_raw_text = "\n\n".join(raw_full_texts)
    
    # 3. Dynamic Chunking (Prevents context overflow)
    text_chunks = chunk_text(combined_raw_text, chunk_size=2000, overlap=300)
    
    if len(text_chunks) > 3:
        chunk_corpus = [tokenize(chunk) for chunk in text_chunks]
        chunk_bm25 = BM25Okapi(chunk_corpus)
        best_chunks = chunk_bm25.get_top_n(tokenized_query, text_chunks, n=3)
        final_context = "\n\n...[text omitted]...\n\n".join(best_chunks)
    else:
        final_context = combined_raw_text

    return final_context