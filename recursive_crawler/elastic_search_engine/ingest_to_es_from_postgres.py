import os
import json
import psycopg2
from elasticsearch import Elasticsearch, helpers
# Import your Triton embedding function from your engine script
from es_engine import get_query_embedding 
from elasticsearch.helpers import BulkIndexError

# Database connections
es = Elasticsearch("http://localhost:9200")
INDEX_NAME = "bd_gov_chunks"
CHECKPOINT_FILE = "ingestion_checkpoint.txt"

pg_conn = psycopg2.connect(
    dbname="bd_gov_db",
    user="postgres",
    password="password",
    host="localhost",
    port=5432
)

def get_last_checkpoint():
    """Reads the last successfully indexed URL from the checkpoint file."""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return f.read().strip()
    return None

def save_checkpoint(url):
    """Saves the last successfully indexed URL to the checkpoint file."""
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(url)

def create_fresh_index():
    """Creates a clean index with optimized mappings."""
    if es.indices.exists(index=INDEX_NAME):
        print(f"[*] Index '{INDEX_NAME}' already exists. Skipping creation.")
        return

    mapping = {
        "mappings": {
            "properties": {
                "url": {"type": "keyword"},
                "summary": {"type": "text"},
                "keywords": {"type": "keyword"}, 
                "raw_markdown": {"type": "text"},
                "chunk_text": {"type": "text"},  
                "chunk_vector": {"type": "dense_vector", "dims": 768, "index": True, "similarity": "cosine"}
            }
        }
    }
    es.indices.create(index=INDEX_NAME, body=mapping)
    print(f"[+] Fresh index '{INDEX_NAME}' created.")

def run_ingestion():
    cursor = pg_conn.cursor(name="es_export_cursor") 
    last_url = get_last_checkpoint()

    count_cursor = pg_conn.cursor()
    count_cursor.execute("SELECT COUNT(*) FROM websites WHERE status = 'success';")
    total_documents = count_cursor.fetchone()[0]
    count_cursor.close()
    print(f"[*] Total successful documents in PostgreSQL to process: {total_documents}")
    # --------------------------------------------------
    # ১. চেকপয়েন্ট অনুযায়ী কুয়েরি নির্ধারণ (ORDER BY url ইজ মাস্ট)
    if last_url:
        print(f"[*] Resuming ingestion from checkpoint URL: {last_url}")
        # আমরা শুধুমাত্র সেই URL গুলো আনব যেগুলো সর্বশেষ সেভ হওয়া URL এর চেয়ে বড় (lexicographically)
        query = """
            SELECT url, summary, keywords, raw_markdown 
            FROM websites 
            WHERE status = 'success' AND url > %s 
            ORDER BY url ASC;
        """
        cursor.execute(query, (last_url,))
    else:
        print("[*] Starting fresh ingestion from the beginning...")
        create_fresh_index()
        query = """
            SELECT url, summary, keywords, raw_markdown 
            FROM websites 
            WHERE status = 'success' 
            ORDER BY url ASC;
        """
        cursor.execute(query)

    total_indexed = 0

    # ২. ব্যাচ প্রসেসিং এবং চেকপয়েন্ট আপডেট
    while True:
        records = cursor.fetchmany(500) 
        if not records:
            break
            
        actions = []
        last_url_in_batch = None

        for record in records:
            url, summary, keywords_raw, raw_markdown = record
            
            try:
                keywords_list = json.loads(keywords_raw) if keywords_raw else []
            except Exception:
                keywords_list = []
            
            text_to_embed = f"সারসংক্ষেপ: {summary}\n\nবিস্তারিত: {raw_markdown}"
            vector = get_query_embedding(text_to_embed) 
            
            actions.append({
                "_op_type": "index",
                "_index": INDEX_NAME,
                "_id": url, 
                "_source": {
                    "url": url,
                    "summary": summary,
                    "keywords": keywords_list,
                    "raw_markdown": raw_markdown,
                    "chunk_text": raw_markdown, 
                    "chunk_vector": vector
                }
            })
            last_url_in_batch = url

        # ৩. ইলাস্টিকসার্চে পুশ করা
        try:
            # Let's print the dimension of the first vector just to be sure!
            if actions:
                print(f"[*] Debug: The vector dimension from Triton is {len(actions[0]['_source']['chunk_vector'])}")

            success, _ = helpers.bulk(es, actions)
            total_indexed += success
            
            # ৪. পুশ সফল হলে চেকপয়েন্ট আপডেট করা
            if last_url_in_batch:
                save_checkpoint(last_url_in_batch)
                
            print(f"[+] Indexed {total_indexed} documents so far. Checkpoint saved.")
            
        except BulkIndexError as e:
            print(f"\n[!] ELASTICSEARCH REJECTED THE BATCH!")
            print(f"Reason for the first failed document:")
            # This will print the exact reason Elasticsearch threw the error
            print(json.dumps(e.errors[0], indent=2))
            break
            
        except Exception as e:
            print(f"[!] General Batch indexing failed. Error: {e}")
            break

    cursor.close()
    
    # ইনজেশন সম্পূর্ণ হলে চেকপয়েন্ট ফাইলটি মুছে ফেলা (যাতে ভবিষ্যতে আবার ফ্রেশ রান করা যায়)
    if not records:
        print("\n[+] Data ingestion completely finished!")
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)

if __name__ == "__main__":
    run_ingestion()