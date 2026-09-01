import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import psycopg2
from psycopg2 import pool
import os
import psutil
import datetime

from db_setup import DB_CONFIG
from extractor import is_javascript_heavy, extract_keywords, generate_snippet
from parsers import parse_with_crawl4ai, parse_with_markdownify
import change_detection as cd

SEED_FILE = "data/crawled_alive_gov_bd_sites(_district_level).txt" # Your text file with 1 URL per line

# ==========================================
# CONCURRENCY LIMITS
# ==========================================
# 🚦 Hard-cap the concurrent headless browser instances.
# 5 browsers * ~600MB max = ~3GB RAM dedicated to browser scraping.
BROWSER_SEMAPHORE = asyncio.Semaphore(10)

# ==========================================
# DATABASE CONNECTION POOL
# ==========================================
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
                        INSERT INTO seed_websites (website_url, status) 
                        VALUES (%s, 'pending') ON CONFLICT (website_url) DO NOTHING;
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
# QUEUE MANAGEMENT (INNER LOOP & SCAVENGER)
# ==========================================
def get_global_pending_counts():
    """Returns the total remaining seeds and pages to prevent premature shutdown."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM seed_websites WHERE status = 'pending';")
        seeds = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM spider_queue WHERE status = 'pending';")
        pages = cursor.fetchone()[0]
        return seeds, pages
    except Exception:
        return 0, 0
    finally:
        release_db_connection(conn)

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

def get_any_pending_webpage():
    """SCAVENGER MODE: Grabs ANY pending page from the queue regardless of domain."""
    conn = get_db_connection()
    result = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE spider_queue SET status = 'processing' 
            WHERE url = (
                SELECT url FROM spider_queue 
                WHERE status = 'pending' 
                ORDER BY added_at ASC LIMIT 1 
                FOR UPDATE SKIP LOCKED
            ) RETURNING url, base_domain;
        """)
        result = cursor.fetchone()
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"  [!] DB Error in get_any_pending_webpage: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)
    return result # Returns (url, base_domain) or None

def add_urls_to_queue(urls, base_domain):
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
# DATA SAVING  (change-detection aware)
# ==========================================
def save_crawled_data(url, markdown, source_hash=None, etag=None,
                      last_modified=None, is_js_heavy=None):
    """Write a changed/new page, recording hashes + HTTP validators so future
    crawls can skip it while it stays unchanged."""
    snippet = generate_snippet(markdown)
    keywords = extract_keywords(markdown)
    conn = get_db_connection()
    try:
        cd.upsert_content(conn, url, markdown, snippet, keywords,
                          source_hash, etag, last_modified, is_js_heavy)
    except Exception as e:
        print(f"  [!] DB Error in save_crawled_data: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)


def _db_get_row_state(url):
    conn = get_db_connection()
    try:
        return cd.get_row_state(conn, url)
    except Exception:
        return None
    finally:
        release_db_connection(conn)


def _db_record_unchanged(url, source_hash, etag, last_modified, is_js_heavy):
    conn = get_db_connection()
    try:
        cd.record_unchanged(conn, url, source_hash, etag, last_modified, is_js_heavy)
    except Exception as e:
        print(f"  [!] DB Error in record_unchanged: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)


def _db_touch_last_checked(url):
    conn = get_db_connection()
    try:
        cd.touch_last_checked(conn, url)
    except Exception:
        conn.rollback()
    finally:
        release_db_connection(conn)

# ==========================================
# CORE PROCESSING
# ==========================================
async def process_url(url, base_domain):
    print(f"    -> Crawling: {url}")

    # --- CHANGE DETECTION: gate 1 (HTTP conditional) --------------------------
    stored = _db_get_row_state(url)
    req_headers = cd.conditional_headers(stored)
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=req_headers)
            if response.status_code == 304:
                # Server confirms the page is unchanged -> skip parse + write.
                print(f"      [=] 304 Not Modified. Skipping (unchanged): {url}")
                _db_touch_last_checked(url)
                return []
            html_content = response.text
    except Exception as e:
        print(f"      [!] HTTP Error: {e}")
        return []

    # Capture validators + raw-HTML hash for the remaining gates.
    etag = response.headers.get("ETag")
    last_modified = response.headers.get("Last-Modified")
    source_hash = cd.sha256_text(html_content)

    soup = BeautifulSoup(html_content, 'html.parser')

    discovered_links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        full_url = urljoin(url, href).split('#')[0]
        
        # [ ... All your existing Trap Killers remain active here ... ]
        if 'accessibledictionary.gov.bd' in full_url.lower(): continue
        if '<' in full_url or '>' in full_url or '{' in full_url or '[' in full_url: continue
        if len(full_url) > 250: continue
        
        path_segments = [seg for seg in urlparse(full_url).path.split('/') if seg]
        if any(path_segments.count(seg) > 2 for seg in path_segments): continue
        if 'nolink' in full_url.lower(): continue
        if ' ' in full_url or '%20' in full_url: continue
        
        url_path = urlparse(full_url).path.lower()
        if '.gov.bd' in url_path or '.com' in url_path: continue
        if any(media_word in url_path for media_word in ['/photo', '/gallery', '/video', '/image']): continue
        if any(cms_tag in url_path for cms_tag in ['/node/', '/mlid/', '/site/eservices/', '/site/field_office/', '/views/', '/site/education_institute/']): continue
        if any(koha_tag in url_path for koha_tag in ['opac-search.pl', 'opac-export.pl', 'opac-isbddetail.pl', 'tracklinks.pl', 'opac-reserve.pl', 'opac-detail.pl']): continue
        if 'search_operative_tariff' in full_url.lower() or 'download=' in full_url.lower(): continue
        if '/search/all/' in url_path or '/search?' in full_url.lower() or 'separator' in full_url.lower(): continue
        if ';jsessionid=' in full_url.lower(): continue
        if 'eyJpdiI6' in full_url or '/passport_details/' in url_path or '/application/' in url_path: continue
        if '/cdn-cgi/' in url_path or 'response_type=code' in full_url.lower(): continue
        if any(db_trap in url_path for db_trap in ['/web_site/notice_details/', '/web_site/nis_details/', '/exporter/', '/edirectory-district-listing/', '/show-bibidh-info/']): continue
        if full_url.endswith('==') or '%f2' in full_url.lower(): continue
        if 'session=' in full_url.lower() or '&cs=' in full_url.lower() or '?lang=' in full_url.lower(): continue
        if '-print-' in url_path: continue

        sav_folders = ['home', 'main', 'notice', 'index.php']
        if any(url_path.lower().count(f) > 1 for f in sav_folders): continue
        if '/group-details/' in url_path or '/unit-details/' in url_path or '/edirectory-' in url_path: continue
            
        sreda_folders = ['irsc', 'nem', 'locallab', 'intllab', 'stakeholder', 'login', 'view', 'noc']
        if any(folder in url_path for folder in sreda_folders) and any(url_path.count(folder) > 1 for folder in sreda_folders): continue

        if any(ext in full_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '/wp-content/uploads/']): continue
        if any(db in url_path for db in ['/bridgedatabase/', '/unit-details/', '/operative-tariff/details/', '/hs-code-details/']): continue
        if '/assesment_home/' in url_path.lower() or '/main/home/' in url_path.lower(): continue
        if '/nem/' in url_path and url_path.count('nem') > 1: continue

        if any(registry in url_path for registry in ['/public-report/establishment/', '/content/details/', '/profile/', '/contents/pictures', '/success-story/details/']): continue
        if 'username=' in full_url.lower(): continue
        if 'page_name=elibrary' in full_url.lower() and '&page=' in full_url.lower(): continue

        if full_url.startswith(base_domain) and not full_url.endswith(('.pdf', '.zip', '.doc', '.xlsx')):
            discovered_links.add(full_url)
            
    # ==========================================
    # PARSER ROUTING + CHANGE-DETECTION GATES
    # ==========================================
    js_heavy = is_javascript_heavy(soup)

    # --- gate 2 (raw-HTML hash, STATIC pages only) ---------------------------
    # A static page whose HTML is byte-identical to last time cannot have changed
    # content -> skip the parse and the write entirely (the big win at scale).
    if cd.classify_decision(js_heavy, source_hash, stored) == "skip_unchanged":
        print(f"      [=] Unchanged HTML (static). Skipping parse+write: {url}")
        _db_record_unchanged(url, source_hash, etag, last_modified, js_heavy)
        return list(discovered_links)

    if js_heavy:
        # 🚦 THE CONCURRENCY BOUNCER
        async with BROWSER_SEMAPHORE:
            print(f"      [🚦] Browser Slot Acquired -> {url}")
            final_markdown = await parse_with_crawl4ai(url)
    else:
        # Static runs instantly
        final_markdown = parse_with_markdownify(html_content)

    if final_markdown:
        md_lower = final_markdown.lower().strip()

        if "just a moment" in md_lower or "enable javascript and cookies" in md_lower or "cloudflare" in md_lower:
            print(f"      [!] Cloudflare Bot Trap Detected! Discarding payload.")
            return list(discovered_links)

        if len(md_lower) < 50:
            print(f"      [!] Payload too small ({len(md_lower)} chars). Discarding.")
            return list(discovered_links)

        # --- gate 3 (markdown hash) ------------------------------------------
        # Content identical despite an HTML wrapper diff (rotating token, ad slot,
        # or JS-heavy re-render) -> refresh validators but skip the row rewrite.
        md_hash = cd.sha256_text(final_markdown)
        if cd.write_decision(md_hash, stored) == "skip_unchanged":
            print(f"      [=] Unchanged content (markdown hash match). Skipping write: {url}")
            _db_record_unchanged(url, source_hash, etag, last_modified, js_heavy)
            return list(discovered_links)

        save_crawled_data(url, final_markdown,
                          source_hash=source_hash, etag=etag,
                          last_modified=last_modified, is_js_heavy=js_heavy)
        print(f"      [+] Updated (content changed): {url}")

    return list(discovered_links)


async def fleet_memory_monitor(interval=30, log_file="data/fleet_memory.log"):
    main_process = psutil.Process(os.getpid())
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*50}\n🚀 NEW FLEET LAUNCHED: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*50}\n")

    while True:
        try:
            total_mem = main_process.memory_info().rss
            for child in main_process.children(recursive=True):
                total_mem += child.memory_info().rss
                
            mem_mb = total_mem / 1024 / 1024
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_message = f"[{timestamp}] 🖥️ [FLEET VITAL] Total System RAM: {mem_mb:.2f} MB\n"
            
            print(log_message.strip())
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_message)
            
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
        await asyncio.sleep(interval)   

# ==========================================
# ORCHESTRATOR
# ==========================================
async def run_domain_spider():
    load_seeds_from_txt()
    # Make sure the incremental-crawl columns exist before any worker writes.
    _conn = get_db_connection()
    try:
        cd.ensure_hash_columns(_conn)
    finally:
        release_db_connection(_conn)
    print("\n🚀 Starting Spider Fleet...\n")
    
    while True:
        current_website = get_next_pending_website()
        
        # ----------------------------------------------------
        # 1. NORMAL DOMAIN PROCESSING
        # ----------------------------------------------------
        if current_website:
            print("="*50)
            print(f"[*] STARTING NEW DOMAIN: {current_website}")
            print("="*50)
            
            add_urls_to_queue([current_website], current_website)
            
            while True:
                current_webpage = get_next_pending_webpage(current_website)
                
                if not current_webpage:
                    print(f"[+] Domain exhausted. Finishing up: {current_website}")
                    mark_website_completed(current_website)
                    break 
                    
                try:
                    new_links = await process_url(current_webpage, current_website)
                    add_urls_to_queue(new_links, current_website)
                    update_webpage_status(current_webpage, 'completed')
                except Exception as e:
                    print(f"      [!] Error processing {current_webpage}: {e}")
                    update_webpage_status(current_webpage, 'failed')
                    
                await asyncio.sleep(0.5)

        # ----------------------------------------------------
        # 2. SCAVENGER MODE (The Deadlock Fix)
        # ----------------------------------------------------
        else:
            pending_seeds, pending_pages = get_global_pending_counts()
            
            if pending_seeds == 0 and pending_pages == 0:
                print("[*] 🏁 All seed domains and internal pages have been completely crawled! Shutting down.")
                break
                
            # If seeds are out but pages remain, pivot to scavenger mode to hunt orphans
            scavenger_result = get_any_pending_webpage()
            
            if scavenger_result:
                orphan_url, orphan_domain = scavenger_result
                print(f"[*] SCAVENGER MODE: Picked up orphaned page -> {orphan_url}")
                try:
                    new_links = await process_url(orphan_url, orphan_domain)
                    add_urls_to_queue(new_links, orphan_domain)
                    update_webpage_status(orphan_url, 'completed')
                except Exception as e:
                    print(f"      [!] Error processing {orphan_url}: {e}")
                    update_webpage_status(orphan_url, 'failed')
            else:
                # Pages exist but are actively being processed by other workers. Just wait.
                await asyncio.sleep(5)


async def main():
    monitor_task = asyncio.create_task(fleet_memory_monitor(interval=30, log_file="data/fleet_memory.log"))
    
    print("🚀 Launching fleet...")
    await run_domain_spider() 
    
    monitor_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())