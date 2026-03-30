import asyncio
import asyncpg
import re
from tqdm.asyncio import tqdm

# ---------------- CONFIGURATION ---------------- #
DB_USER = "postgres"         
DB_PASS = "password"         
DB_NAME = "bd_gov_db"        
DB_HOST = "127.0.0.1"
DB_PORT = 5432               
# ----------------------------------------------- #

def extract_markdown_links(markdown_text, base_url):
    """Extracts all valid HTTP/HTTPS links from markdown text."""
    pattern = r'\[.*?\]\((https?://[^\s\)]+)\)'
    raw_links = re.findall(pattern, markdown_text)
    
    clean_links = set()
    for link in raw_links:
        # 1. Ignore absurdly long junk URLs (PostgreSQL B-Tree index limit)
        if len(link) > 2000:
            continue
            
        # 2. Ignore self-referencing links or anchor tags
        if link != base_url and not link.startswith(f"{base_url}/#"):
            clean_links.add(link)
            
    return list(clean_links)

async def process_batch(pool, records):
    """Extracts links and saves them to the website_links table."""
    link_query = """
        INSERT INTO website_links (source_url, target_url)
        VALUES ($1, $2)
        ON CONFLICT (source_url, target_url) DO NOTHING;
    """
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            for record in records:
                source_url = record['url']
                markdown = record['raw_markdown']
                
                if markdown:
                    links = extract_markdown_links(markdown, source_url)
                    for target in links:
                        await conn.execute(link_query, source_url, target)

async def main():
    print("[*] Connecting to PostgreSQL...")
    pool = await asyncpg.create_pool(user=DB_USER, password=DB_PASS, database=DB_NAME, host=DB_HOST, port=DB_PORT)
    
    # Ensure the links table exists
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS website_links (
                id SERIAL PRIMARY KEY,
                source_url TEXT REFERENCES websites(url) ON DELETE CASCADE,
                target_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_url, target_url) 
            )
        ''')
        
        print("[*] Fetching all completed markdown records from the database...")
        records = await conn.fetch("SELECT url, raw_markdown FROM websites WHERE status = 'success' AND raw_markdown IS NOT NULL")
        
    print(f"[*] Found {len(records)} websites to process. Extracting links...")
    
    # Process in batches of 100 for speed
    batch_size = 100
    batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    
    for batch in tqdm(batches, desc="Populating Links Table"):
        await process_batch(pool, batch)
        
    print("\n[+] Retroactive link extraction complete! Your graph database is populated.")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())