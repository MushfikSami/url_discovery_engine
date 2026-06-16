import json
import psycopg2
from urllib.parse import urlparse

# Database configuration - adjust if your postgres uses a specific user/password
DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",       # Change if your DB user is different
    "password": "password",   # Change if your DB has a password
    "host": "localhost",
    "port": "5432"
}

def normalize_domain(url):
    """Extracts and normalizes the base domain for accurate comparison."""
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    domain = urlparse(url).netloc.lower()
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain

def check_against_db():
    print("🚀 Starting Database Cross-Reference...")

    # 1. Load scraped links from JSON
    try:
        with open("extracted_bdgovlinks.json", "r", encoding="utf-8") as f:
            scraped_links = json.load(f).get("gov_links", [])
    except FileNotFoundError:
        print("❌ Error: 'extracted_bdgovlinks.json' not found.")
        return

    # Normalize scraped domains and map them back to their original URLs
    # so we have valid URLs to feed the crawler later.
    scraped_domain_map = {}
    for link in scraped_links:
        domain = normalize_domain(link)
        # Keep the shortest URL for the domain as the seed
        if domain not in scraped_domain_map or len(link) < len(scraped_domain_map[domain]):
            scraped_domain_map[domain] = link

    # 2. Fetch existing domains from PostgreSQL
    existing_domains = set()
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Query the seed_websites table
        cursor.execute("SELECT website_url FROM seed_websites;")
        rows = cursor.fetchall()
        
        for row in rows:
            db_url = row[0]
            existing_domains.add(normalize_domain(db_url))
            
        cursor.close()
        conn.close()
        print(f"📦 Loaded {len(existing_domains)} seed domains from 'gov_spider_db'.")
        
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return

    # 3. Compare the sets
    scraped_domains = set(scraped_domain_map.keys())
    
    new_domains = scraped_domains - existing_domains
    duplicate_domains = scraped_domains.intersection(existing_domains)

    # 4. Report and Export
    print("\n" + "="*40)
    print("📊 POSTGRESQL RECONCILIATION REPORT")
    print("="*40)
    print(f"✅ Already in DB (Duplicates): {len(duplicate_domains)}")
    print(f"🌟 Brand New Domains Found:  {len(new_domains)}")

    if new_domains:
        # Extract the original URLs for the new domains
        new_seed_urls = [scraped_domain_map[domain] for domain in new_domains]
        
        # Save to a text file formatted exactly for your crawler's input
        output_file = "new_seed_websites.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            for url in sorted(new_seed_urls):
                f.write(f"{url}\n")
                
        print(f"\n💾 Saved {len(new_domains)} new URLs to '{output_file}'")
        print("   -> You can append these to 'data/crawled_alive_gov_bd_sites.txt'")
        
        # Quick preview
        print("\n🔍 Preview of New Domains:")
        for url in new_seed_urls[:5]:
            print(f"  - {url}")

if __name__ == "__main__":
    check_against_db()