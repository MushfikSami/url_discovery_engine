# utils.py
import re

def flatten_tree(nodes_list):
    flat_list = []
    for node in nodes_list:
        flat_list.append(node)
        if 'nodes' in node and isinstance(node['nodes'], list):
            flat_list.extend(flatten_tree(node['nodes']))
    return flat_list

def tokenize(text):
    if not text: return []
    return re.findall(r'\w+', str(text).lower())

def chunk_text(text, chunk_size=2000, overlap=300):
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks