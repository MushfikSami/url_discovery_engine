# loader.py

try:
    from database import insert_pending_url
    from config import TARGET_FILE
except ModuleNotFoundError:
    from .database import insert_pending_url
    from .config import TARGET_FILE

def load_urls_from_txt():
    """Reads URLs from a plain text file and inserts them into the DB."""
    print(f"[*] Loading URLs from {TARGET_FILE} into the database...")
    
    total_loaded = 0
    try:
        # errors='replace' prevents crashes from corrupted characters
        with open(TARGET_FILE, mode='r', encoding='utf-8', errors='replace') as file:
            for line in file:
                url = line.strip()
                if not url:
                    continue
                
                insert_pending_url(url)
                total_loaded += 1
                
        print(f"[+] Successfully loaded {total_loaded} URLs into the queue.")
    except Exception as e:
        print(f"[!] Error reading text file: {e}")