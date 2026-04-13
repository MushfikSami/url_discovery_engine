from elasticsearch import Elasticsearch

# Connect to Elasticsearch
es = Elasticsearch("http://localhost:9200")
INDEX_NAME = "bd_gov_chunks"

def delete_index():
    try:
        # Check if the index exists
        if es.indices.exists(index=INDEX_NAME):
            print(f"[*] Deleting existing index '{INDEX_NAME}'...")
            es.indices.delete(index=INDEX_NAME)
            print("[+] Index successfully deleted! Disk space freed.")
        else:
            print(f"[-] Index '{INDEX_NAME}' does not exist.")
    except Exception as e:
        print(f"[!] Error deleting index: {e}")

if __name__ == "__main__":
    # WARNING: This is irreversible.
    confirmation = input(f"Are you sure you want to permanently delete '{INDEX_NAME}'? (y/n): ")
    if confirmation.lower() == 'y':
        delete_index()
    else:
        print("Operation cancelled.")