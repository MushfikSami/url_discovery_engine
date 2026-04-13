import asyncio
import csv
import psycopg2
from crawl4ai import AsyncWebCrawler

# ==========================================
# 1. DATABASE SETUP
# ==========================================
DB_CONFIG = {
    "dbname": "gov_bd_db", # Change to a fresh DB if preferred
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

def setup_database():
    """Creates the gov_bd_pages table."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gov_bd_pages (
                url TEXT PRIMARY KEY,
                title TEXT,
                markdown_body TEXT,
                status VARCHAR(50) DEFAULT 'pending',
                crawled_at TIMESTAMP
            );
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("[+] Database table 'gov_bd_pages' is ready.")
    except Exception as e:
        print(f"[!] Database setup failed: {e}")

def update_db_status(url, title, markdown, status):
    """Updates a specific URL with its crawled content."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE gov_bd_pages 
            SET title = %s, markdown_body = %s, status = %s, crawled_at = CURRENT_TIMESTAMP
            WHERE url = %s;
        """, (title, markdown, status, url))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[!] Failed to update DB for {url}: {e}")

# ==========================================
# 2. PHASE 1: LOAD URLS FROM CSV
# ==========================================
# ==========================================
# 2. PHASE 1: LOAD URLS FROM TXT
# ==========================================
def load_urls_from_txt(txt_filepath):
    """Reads URLs from a plain text file (one per line) and inserts them as 'pending'."""
    print(f"[*] Loading URLs from {txt_filepath} into the database...")
    
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    total_loaded = 0
    
    try:
        # errors='replace' prevents crashes if any weird characters snuck into the txt file
        with open(txt_filepath, mode='r', encoding='utf-8', errors='replace') as file:
            for line in file:
                url = line.strip() # Removes newlines and spaces
                
                # Skip empty lines just in case
                if not url:
                    continue
                
                # Insert safely, ignoring if it's already there
                cursor.execute("""
                    INSERT INTO gov_bd_pages (url, status) 
                    VALUES (%s, 'pending') 
                    ON CONFLICT (url) DO NOTHING;
                """, (url,))
                total_loaded += 1
                
        conn.commit()
        print(f"[+] Successfully loaded {total_loaded} URLs into the queue.")
    except Exception as e:
        print(f"[!] Error reading text file: {e}")
    finally:
        cursor.close()
        conn.close()
# ==========================================
# 3. PHASE 2: THE CRAWLER
# ==========================================
async def process_pending_urls():
    """Fetches 'pending' URLs from Postgres and crawls them."""
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM gov_bd_pages WHERE status = 'pending';")
    pending_urls = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    
    if not pending_urls:
        print("[*] No pending URLs to crawl. You are all caught up!")
        return

    print(f"[*] Starting crawler for {len(pending_urls)} pending pages...")
    
    async with AsyncWebCrawler(verbose=False) as crawler:
        for url in pending_urls:
            print(f"  -> Crawling: {url}")
            try:
                # Rely on generic heuristic extraction, but aggressively exclude UI tags
                result = await crawler.arun(
                    url=url,
                    excluded_tags=["nav", "footer", "header", "aside", "form", "script", "style", "noscript"],
                    word_count_threshold=20, # Ignore pages with almost no text
                    bypass_cache=False # False is fine here since it's our first run on these URLs
                )
                
                if result.success:
                    # Generic pages don't always have clean titles in the URL, 
                    # so we will try to grab the title from the crawler's extracted metadata
                    title = getattr(result, 'title', url) 
                    
                    update_db_status(url, title, result.markdown, "success")
                else:
                    update_db_status(url, "", "", "failed")
                    
            except Exception as e:
                update_db_status(url, "", "", "error")
                print(f"     [!] Error: {e}")
            
            # Politeness delay
            await asyncio.sleep(0.5)

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
async def main():
    setup_database()
    
    # 1. Provide the path to your filtered 39k URL CSV here:
    txt_file = "crawled_alive_gov_bd_sites.txt" 
    
    # Comment this out after the first successful load so it doesn't re-read the CSV every time
    load_urls_from_txt(txt_file)
    
    # 2. Start the resilient crawler
    await process_pending_urls()

if __name__ == "__main__":
    asyncio.run(main())