# spider.py
import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import psycopg2
from psycopg2 import pool
import os

from db_setup import DB_CONFIG
from extractor import is_javascript_heavy, extract_keywords, generate_snippet
from parsers import parse_with_crawl4ai, parse_with_markdownify

SEED_FILE = "data/crawled_alive_gov_bd_sites.txt" # Your text file with 1 URL per line

# ==========================================
# DATABASE CONNECTION POOL
# ==========================================
# Initialize a thread-safe connection pool for this worker
# (min connections = 1, max connections = 10)
try:
    db_pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **DB_CONFIG)
except Exception as e:
    print(f"[!] Failed to initialize database pool: {e}")
    exit(1)

def get_db_connection():
    return db_pool.getconn()

def release_db_connection(conn):
    if conn:
        db_pool.putconn(conn)

# ==========================================
# UTILITIES
# ==========================================
def get_base_domain(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"

# ==========================================
# SEED MANAGEMENT (OUTER LOOP)
# ==========================================
def load_seeds_from_txt():
    """Loads URLs from your text file into the seed_websites table."""
    if not os.path.exists(SEED_FILE):
        print(f"[!] Warning: {SEED_FILE} not found. Assuming seeds are already in DB.")
        return

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        with open(SEED_FILE, 'r') as f:
            for line in f:
                url = line.strip()
                if url:
                    cursor.execute("""
                        INSERT INTO seed_websites (website_url) 
                        VALUES (%s) ON CONFLICT (website_url) DO NOTHING;
                    """, (url,))
        conn.commit()
        cursor.close()
        print(f"[*] Seeds loaded from {SEED_FILE}.")
    except Exception as e:
        print(f"  [!] DB Error in load_seeds: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)

def get_next_pending_website():
    """Gets the next top-level website from the seed list."""
    conn = get_db_connection()
    result = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE seed_websites SET status = 'processing' 
            WHERE website_url = (
                SELECT website_url FROM seed_websites 
                WHERE status = 'pending' LIMIT 1 
                FOR UPDATE SKIP LOCKED
            ) RETURNING website_url;
        """)
        result = cursor.fetchone()
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in get_next_pending_website: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)
    return result[0] if result else None

def mark_website_completed(website_url):
    """Marks a top-level website as completely crawled."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE seed_websites SET status = 'completed' WHERE website_url = %s;", (website_url,))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in mark_website_completed: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)

# ==========================================
# QUEUE MANAGEMENT (INNER LOOP)
# ==========================================
def get_next_pending_webpage(base_domain):
    """Gets the next webpage specifically for the CURRENT active domain."""
    conn = get_db_connection()
    result = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE spider_queue SET status = 'processing' 
            WHERE url = (
                SELECT url FROM spider_queue 
                WHERE status = 'pending' AND base_domain = %s 
                ORDER BY added_at ASC LIMIT 1 
                FOR UPDATE SKIP LOCKED
            ) RETURNING url;
        """, (base_domain,))
        result = cursor.fetchone()
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in get_next_pending_webpage: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)
    return result[0] if result else None

def add_urls_to_queue(urls, base_domain):
    """Inserts newly discovered URLs into the queue attached to their base domain."""
    if not urls: return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO spider_queue (url, base_domain, status) 
            VALUES (%s, %s, 'pending') 
            ON CONFLICT (url) DO NOTHING;
        """
        cursor.executemany(query, [(url, base_domain) for url in urls])
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in add_urls_to_queue: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)

def update_webpage_status(url, status):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE spider_queue SET status = %s WHERE url = %s;", (status, url))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in update_webpage_status: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)

# ==========================================
# DATA SAVING
# ==========================================
def update_domain_hierarchy(website, new_url):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO domain_hierarchy (website, web_pages) 
            VALUES (%s, ARRAY[%s])
            ON CONFLICT (website) 
            DO UPDATE SET web_pages = array_append(domain_hierarchy.web_pages, %s)
            WHERE NOT (%s = ANY(domain_hierarchy.web_pages));
        """, (website, new_url, new_url, new_url))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in update_domain_hierarchy: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)

def save_crawled_data(url, markdown):
    snippet = generate_snippet(markdown)
    keywords = extract_keywords(markdown)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO crawled_data (url, raw_markdown, snippet, keywords) 
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE 
            SET raw_markdown = EXCLUDED.raw_markdown,
                snippet = EXCLUDED.snippet,
                keywords = EXCLUDED.keywords;
        """, (url, markdown, snippet, keywords))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in save_crawled_data: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)

# ==========================================
# CORE PROCESSING
# ==========================================
async def process_url(url, base_domain):
    print(f"    -> Crawling: {url}")
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            html_content = response.text
    except Exception as e:
        print(f"      [!] HTTP Error: {e}")
        return []

    soup = BeautifulSoup(html_content, 'html.parser')
    
    discovered_links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(url, href).split('#')[0]
        
        # Only keep links belonging to the exact same base domain
        if full_url.startswith(base_domain) and not full_url.endswith(('.pdf', '.zip', '.doc', '.xlsx')):
            discovered_links.add(full_url)
            update_domain_hierarchy(base_domain, full_url)

    if is_javascript_heavy(soup):
        final_markdown = await parse_with_crawl4ai(url)
    else:
        final_markdown = parse_with_markdownify(html_content)

    if final_markdown:
        save_crawled_data(url, final_markdown)
    
    return list(discovered_links)

# ==========================================
# ORCHESTRATOR
# ==========================================
async def run_domain_spider():
    # 1. Load the text file into the seed table
    load_seeds_from_txt()
    
    print("\n🚀 Starting Domain-by-Domain Spider...\n")
    
    while True:
        # OUTER LOOP: Get the next website
        current_website = get_next_pending_website()
        
        if not current_website:
            print("[*] All websites in the text file have been fully crawled! Shutting down.")
            break
            
        print("="*50)
        print(f"[*] STARTING NEW DOMAIN: {current_website}")
        print("="*50)
        
        # Inject the root domain into the spider queue to kick off the inner loop
        add_urls_to_queue([current_website], current_website)
        
        # INNER LOOP: Crawl all pages belonging to THIS domain
        while True:
            current_webpage = get_next_pending_webpage(current_website)
            
            if not current_webpage:
                print(f"[+] Domain exhausted. Finishing up: {current_website}")
                mark_website_completed(current_website)
                break # Exit the inner loop, move to the next website
                
            try:
                new_links = await process_url(current_webpage, current_website)
                add_urls_to_queue(new_links, current_website)
                update_webpage_status(current_webpage, 'completed')
            except Exception as e:
                print(f"      [!] Error processing {current_webpage}: {e}")
                update_webpage_status(current_webpage, 'failed')
                
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(run_domain_spider())