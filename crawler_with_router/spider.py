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
        # Clean whitespace and strip anchor tags
        href = a_tag['href'].strip()
        full_url = urljoin(url, href).split('#')[0]
        
        # ==========================================
        # THE TRAP KILLERS
        # ==========================================
        # 0. The Radioactive Ghost (Block the dictionary even if cross-linked)
        if 'accessibledictionary.gov.bd' in full_url.lower():
            continue

        # 1. Block HTML/JS Injection (The Frankenstein Killer)
        if '<' in full_url or '>' in full_url or '{' in full_url or '[' in full_url:
            continue
            
        # 2. Block Insanely Long URLs (The Infinite Loop Killer)
        if len(full_url) > 250:
            continue
            
        # 3. Block Path Recursion (e.g. /site/view/site/view/site/view)
        path_segments = [seg for seg in urlparse(full_url).path.split('/') if seg]
        if any(path_segments.count(seg) > 2 for seg in path_segments):
            continue
            
        # 4. Block a2i Template 'nolink' Bug
        if 'nolink' in full_url.lower():
            continue
            
        # 5. Block unencoded spaces (broken template hrefs)
        if ' ' in full_url or '%20' in full_url:
            continue

        # 6. Block the "Relative Domain" Trap
        url_path = urlparse(full_url).path.lower()
        if '.gov.bd' in url_path or '.com' in url_path:
            continue

        # 7. Block RAG Poison (Media Galleries, Photos, Videos)
        if any(media_word in url_path for media_word in ['/photo', '/gallery', '/video', '/image']):
            continue

        # 8. Block a2i CMS Dynamic Routing Loops (Including Views & Education)
        if any(cms_tag in url_path for cms_tag in ['/node/', '/mlid/', '/site/eservices/', '/site/field_office/', '/views/', '/site/education_institute/']):
            continue

        # 9. Application Traps (Search Engines, Metadata Exports, & Downloads)
        if any(koha_tag in url_path for koha_tag in ['opac-search.pl', 'opac-export.pl', 'opac-isbddetail.pl', 'tracklinks.pl', 'opac-reserve.pl', 'opac-detail.pl']):
            continue
        if 'search_operative_tariff' in full_url.lower() or 'download=' in full_url.lower():
            continue
            
        # 10. Avoid generic search result pages (SERPs)
        if '/search/all/' in url_path or '/search?' in full_url.lower() or 'separator' in full_url.lower():
            continue
        

        # 11. The a2i Template 'Separator' Bug
        # Used for drawing lines in dropdown menus, creates infinite CMS loops
        if 'separator' in full_url.lower():
            continue

        # 11. Block Java Session IDs (Tracking Traps)
        if ';jsessionid=' in full_url.lower():
            continue

        # 12. Block Laravel Encrypted Payloads & App Trackers
        # 'eyJpdiI6' is Base64 for '{"iv":'
        if 'eyJpdiI6' in full_url or '/passport_details/' in url_path or '/application/' in url_path:
            continue

        # 13. Block Cloudflare Bot Challenges & OAuth Login Loops
        if '/cdn-cgi/' in url_path or 'response_type=code' in full_url.lower():
            continue

        # 14. Block Encrypted App Routing & Massive Public Databases (RAG Poison)
        if any(db_trap in url_path for db_trap in ['/web_site/notice_details/', '/web_site/nis_details/', '/exporter/', '/edirectory-district-listing/', '/show-bibidh-info/']):
            continue
        if full_url.endswith('==') or '%f2' in full_url.lower():
            continue

        # 15. Block Session IDs & Print Views (Duplicate Content)
        if 'session=' in full_url.lower() or '&cs=' in full_url.lower() or '?lang=' in full_url.lower():
            continue
        if '-print-' in url_path:
            continue

        # 16. Block Custom App Loops & Directories
        # The Savar Death Spiral
        sav_folders = ['home', 'main', 'notice', 'index.php']
        if any(url_path.lower().count(f) > 1 for f in sav_folders):
            continue
        
        # The Scout Hydra
        if '/group-details/' in url_path or '/unit-details/' in url_path or '/edirectory-' in url_path:
            continue
            
        # The SREDA Shuffle (Updated)
        sreda_folders = ['irsc', 'nem', 'locallab', 'intllab', 'stakeholder', 'login', 'view', 'noc']
        if any(folder in url_path for folder in sreda_folders) and any(url_path.count(folder) > 1 for folder in sreda_folders):
            continue

        # 17. Hard Block Media Extensions & Deep DBs (RAG Poison)
        if any(ext in full_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '/wp-content/uploads/']):
            continue
        if any(db in url_path for db in ['/bridgedatabase/', '/unit-details/', '/operative-tariff/details/', '/hs-code-details/']):
            continue

        # 18. CMS Deep Routing Loops (Savar Mutations & SREDA)
        if '/assesment_home/' in url_path.lower() or '/main/home/' in url_path.lower():
            continue
        if '/nem/' in url_path and url_path.count('nem') > 1:
            continue

        # 19. Block User-Generated Content & Massive Registries
        if any(registry in url_path for registry in ['/public-report/establishment/', '/content/details/', '/profile/', '/contents/pictures', '/success-story/details/']):
            continue
        if 'username=' in full_url.lower():
            continue
        if 'page_name=elibrary' in full_url.lower() and '&page=' in full_url.lower():
            continue
        # ==========================================

        # Only keep links belonging to the exact same base domain
        if full_url.startswith(base_domain) and not full_url.endswith(('.pdf', '.zip', '.doc', '.xlsx')):
            discovered_links.add(full_url)
            
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