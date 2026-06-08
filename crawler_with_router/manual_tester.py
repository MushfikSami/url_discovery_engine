import asyncio
import httpx
from bs4 import BeautifulSoup
import os
import psycopg2
import re
from db_setup import DB_CONFIG

# Import your existing production logic
from extractor import is_javascript_heavy, extract_keywords, generate_snippet
from parsers import parse_with_crawl4ai, parse_with_markdownify

# DB Connection helpers matching your spider setup
def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def fetch_sample_urls(limit=5):
    """Fetches a mix of pending and processed URLs from the live queue for evaluation."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT url, base_domain, status 
            FROM spider_queue 
            ORDER BY RANDOM() 
            LIMIT %s;
        """, (limit,))
        return cursor.fetchall()
    except Exception as e:
        print(f"[!] DB Error fetching from spider_queue: {e}")
        return []
    finally:
        conn.close()

def analyze_table_complexity(soup, html_content):
    """
    Evaluates if a webpage uses highly complex data tables or dynamically generated grids.
    Returns (is_complex, reason_string)
    """
    tables = soup.find_all('table')
    tr_elements = soup.find_all('tr')
    td_elements = soup.find_all('td')
    
    table_count = len(tables)
    tr_count = len(tr_elements)
    td_count = len(td_elements)
    
    # Heuristic 1: High tabular layout density
    if table_count > 3 or tr_count > 20:
        reason = f"High tabular layout density detected ({table_count} tables, {tr_count} rows)."
        return True, reason
        
    # Heuristic 2: Look for indicators of client-side dynamic table rendering frameworks
    html_lower = html_content.lower()
    dynamic_table_signals = [
        'datatable', 'gridview', 'tbody', 'v-data-table', 
        'ngx-datatable', 'ag-grid', 'handsontable'
    ]
    
    found_signals = [sig for sig in dynamic_table_signals if sig in html_lower]
    if found_signals and tr_count < 5:
        reason = f"Dynamic table JS frameworks detected ({', '.join(found_signals)}) with low raw HTML row count ({tr_count})."
        return True, reason

    return False, "Standard text/layout composition."

def generate_safe_filename(url, index):
    """Generates a clean, safe filename unique to each URL using its domain and path."""
    # Strip protocols and special characters
    clean_url = re.sub(r'^https?://(www\.)?', '', url)
    clean_url = re.sub(r'[^a-zA-Z0-9_\-]', '_', clean_url)
    # Truncate to prevent excessively long filenames
    clean_url = clean_url[:40].strip('_')
    return f"inspect_{index:02d}_{clean_url}.md"

async def evaluate_url_pipeline(url, base_domain, current_status, index):
    print("\n" + "="*70)
    print(f"🔍 [DIAGNOSTIC] Evaluating URL [{index}]: {url}")
    print(f"📁 [QUEUE CONTEXT] Domain: {base_domain} | Current Queue Status: {current_status}")
    print("="*70)
    
    # 1. Fetch raw HTML
    try:
        print("📡 Fetching raw page content...")
        async with httpx.AsyncClient(verify=False, timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            html_content = response.text
    except Exception as e:
        print(f"❌ [HTTP Fetch Error]: {e}")
        return
        
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 2. Run Table Complexity Check
    is_complex_table, table_reason = analyze_table_complexity(soup, html_content)
    
    # 3. Standard Router Decision Matrix
    STUBBORN_DOMAINS = ['beza.gov.bd', 'planningcommission.gov.bd', 'landadministration.gov.bd']
    force_headless = any(stubborn in url for stubborn in STUBBORN_DOMAINS)
    is_js_heavy = is_javascript_heavy(soup)
    
    # Final Routing decision
    use_heavy_browser = force_headless or is_js_heavy or is_complex_table
    
    print("\n🚦 [ROUTER ANALYSIS]")
    print(f"   -> Stubborn Domain Rule Match : {force_headless}")
    print(f"   -> JS-Heavy Signature Match   : {is_js_heavy}")
    print(f"   -> Table Complexity Trigger   : {is_complex_table} ({table_reason})")
    
    if use_heavy_browser:
        print("🏆 [ROUTE CHOICE] -> HEAVY BROWSER (Crawl4AI Execution)")
        markdown = await parse_with_crawl4ai(url)
    else:
        print("⚡ [ROUTE CHOICE] -> FAST STATIC (Markdownify Execution)")
        markdown = parse_with_markdownify(html_content)
        
    # 4. Verify Content Integrity
    if not markdown:
        print("\n⚠️ [VERIFICATION FAILED] Payload generated is completely empty.")
        return
        
    md_lower = markdown.lower().strip()
    
    if "just a moment" in md_lower or "cloudflare" in md_lower:
        print("❌ [VERIFICATION FAILED] Captcha/Cloudflare wall visible in output text.")
    elif len(md_lower) < 50:
        print(f"⚠️ [WARNING] Micro-payload generated ({len(md_lower)} chars). Content might be missing.")
    else:
        print(f"✅ [VERIFICATION PASSED] Valid payload generated ({len(markdown)} characters).")

    # 5. Save out to a uniquely named diagnostic markdown file
    output_dir = "data/manual_inspections"
    os.makedirs(output_dir, exist_ok=True)
    
    filename = generate_safe_filename(url, index)
    full_path = os.path.join(output_dir, filename)
    
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(f"# MANUAL INSPECTION REPORT\n")
        f.write(f"- **URL**: {url}\n")
        f.write(f"- **Routing Logic Implemented**: {'Crawl4AI' if use_heavy_browser else 'Markdownify'}\n")
        f.write(f"- **Complexity Profile**: {table_reason}\n")
        f.write(f"- **Extracted Keywords**: {extract_keywords(markdown)}\n")
        f.write("\n" + "="*60 + "\n\n")
        f.write(markdown)
        
    print(f"💾 Rendered layout dumped into distinct file: [ {full_path} ]")

async def main():
    # Setting the limit to 5 records to fulfill your requirement of at least 5 markdown files
    target_limit = 5
    print(f"🔋 Fetching {target_limit} fresh targets from your 'spider_queue' table...")
    records = fetch_sample_urls(limit=target_limit)
    
    if not records:
        print("[!] No entries found or database connection failed. Verify your spider_queue has populated records.")
        return
        
    print(f"📋 Loaded {len(records)} targets. Processing batch...")
    for index, (url, base_domain, status) in enumerate(records, 1):
        await evaluate_url_pipeline(url, base_domain, status, index)
        
        if index < len(records):
            choice = input("\nPress Enter to evaluate the next database URL, or type 'q' to quit: ").strip().lower()
            if choice == 'q':
                print("🛑 Evaluation stopped by user.")
                break
                
    print(f"\n✨ Evaluation complete. Check the directory 'data/manual_inspections/' for all unique markdown results.")

if __name__ == "__main__":
    asyncio.run(main())