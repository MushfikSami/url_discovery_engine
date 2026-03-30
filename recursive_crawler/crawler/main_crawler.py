import asyncio
import json
import asyncpg
from tqdm.asyncio import tqdm
from crawl4ai import AsyncWebCrawler, BrowserConfig
from openai import AsyncOpenAI
import re
# ---------------- CONFIGURATION ---------------- #
DB_USER = "postgres"         
DB_PASS = "password"         
DB_NAME = "bd_gov_db"        
DB_HOST = "127.0.0.1"
DB_PORT = 5432               # Updated to your SSH tunnel port
INPUT_FILE = "crawled_alive_gov_bd_sites.txt"

# vLLM Setup
vllm_client = AsyncOpenAI(base_url="http://localhost:5000/v1", api_key="no-key")
MODEL_NAME = "qwen35"
# ----------------------------------------------- #

async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS websites (
                url TEXT PRIMARY KEY,
                summary TEXT,
                keywords JSONB,
                raw_markdown TEXT,
                status TEXT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

async def get_uncached_urls(pool, input_file):
    try:
        with open(input_file, 'r') as f:
            all_urls = set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        print(f"[!] Input file {input_file} not found.")
        return []

    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT url FROM websites WHERE status IN ('success', 'failed_no_content')")
        cached_urls = set(record['url'] for record in records)

    remaining_urls = list(all_urls - cached_urls)
    return remaining_urls

async def process_with_llm(url, markdown_content):
    truncated_content = markdown_content[:8000] 
    
    # UPDATED PROMPT: Strict instructions and examples in Bengali
    prompt = f"""
    You are an expert data analyst. Read the following markdown extracted from the website: {url}.
    
    Task:
    1. Write a 5-10 sentence summary of what this website is about STRICTLY IN BENGALI (বাংলা).
    2. Extract 5-10 comma-separated keywords representing the main topics STRICTLY IN BENGALI (বাংলা).
    
    Respond STRICTLY in valid JSON format exactly like this example:
    {{
        "summary": "এই ওয়েবসাইটটি বাংলাদেশের সরকারি প্রাথমিক শিক্ষা অধিদপ্তরের অফিসিয়াল পোর্টাল। এখানে শিক্ষা বিষয়ক বিজ্ঞপ্তি এবং অন্যান্য সেবা পাওয়া যায়।",
        "keywords": ["সরকার", "বাংলাদেশ", "শিক্ষা", "প্রাথমিক", "বিজ্ঞপ্তি"]
    }}
    
    Website Markdown:
    {truncated_content}
    """
    
    try:
        response = await vllm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"} 
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("summary", "No summary generated."), json.dumps(result.get("keywords", []))
    except Exception as e:
        tqdm.write(f"[-] LLM processing failed for {url}: {e}")
        return "Error generating summary.", "[]"

async def save_to_db(pool, data, extracted_links=[]):
    """Saves the website data and its relationships to Postgres."""
    
    # 1. Save the main website data
    website_query = """
        INSERT INTO websites (url, summary, keywords, raw_markdown, status, processed_at)
        VALUES ($1, $2, $3::jsonb, $4, $5, CURRENT_TIMESTAMP)
        ON CONFLICT (url) DO UPDATE 
        SET summary = EXCLUDED.summary,
            keywords = EXCLUDED.keywords,
            raw_markdown = EXCLUDED.raw_markdown,
            status = EXCLUDED.status,
            processed_at = CURRENT_TIMESTAMP;
    """
    
    # 2. Save the relationships
    link_query = """
        INSERT INTO website_links (source_url, target_url)
        VALUES ($1, $2)
        ON CONFLICT (source_url, target_url) DO NOTHING;
    """
    
    async with pool.acquire() as conn:
        # Start a transaction so both tables update safely
        async with conn.transaction():
            # Insert the main site
            await conn.execute(website_query, data['url'], data['summary'], data['keywords'], data['raw_markdown'], data['status'])
            
            # Insert all the connections
            for target in extracted_links:
                await conn.execute(link_query, data['url'], target)


async def crawl_and_analyze(url, crawler, pool, semaphore):
    async with semaphore:
        tqdm.write(f"[*] Crawling: {url}")
        try:
            result = await crawler.arun(url=url)
            markdown_content = result.markdown
            
            if not markdown_content or len(markdown_content.strip()) < 50:
                tqdm.write(f"[-] Not enough content found at {url}. Caching as failed.")
                await save_to_db(pool, {
                    "url": url, "summary": "", "keywords": "[]", "raw_markdown": "", "status": "failed_no_content"
                })
                return
                
            summary, keywords_json = await process_with_llm(url, markdown_content)
            
            discovered_links=extract_markdown_links(markdown_content,url)

            await save_to_db(pool, {
                "url": url, 
                "summary": summary, 
                "keywords": keywords_json, 
                "raw_markdown": markdown_content, 
                "status": "success"
            },discovered_links)
            tqdm.write(f"[+] Success & Cached in DB: {url}")
            
        except Exception as e:
            tqdm.write(f"[-] Failed to process {url}: {e}")
            await save_to_db(pool, {
                "url": url, "summary": str(e), "keywords": "[]", "raw_markdown": "", "status": "error"
            })

def extract_markdown_links(markdown_text, base_url):
    """Extracts all valid HTTP/HTTPS links from markdown text."""
    # This regex looks for [Text](URL) and captures the URL part
    pattern = r'\[.*?\]\((https?://[^\s\)]+)\)'
    raw_links = re.findall(pattern, markdown_text)
    
    clean_links = set()
    for link in raw_links:
        # Ignore self-referencing links or anchor tags
        if link != base_url and not link.startswith(f"{base_url}/#"):
            clean_links.add(link)
            
    return list(clean_links)


async def main():
    print("[*] Connecting to PostgreSQL...")
    pool = await asyncpg.create_pool(user=DB_USER, password=DB_PASS, database=DB_NAME, host=DB_HOST, port=DB_PORT)
    
    await init_db(pool)
    urls_to_process = await get_uncached_urls(pool, INPUT_FILE)
    
    if not urls_to_process:
        print("[+] Cache check complete: All URLs have already been processed!")
        await pool.close()
        return

    semaphore = asyncio.Semaphore(5)
    
    # NEW: Browser Configuration for Bengali
    # We set the locale and the Accept-Language header to prioritize Bengali
    browser_config = BrowserConfig(
        
        headers={"Accept-Language": "bn-BD,bn;q=0.9,en-US;q=0.8,en;q=0.7"},
        verbose=False
    )
    
    print(f"[*] Starting Pipeline in BENGALI mode. State is safely cached in PostgreSQL.")
    
    # Pass the browser config into the crawler
    async with AsyncWebCrawler(config=browser_config) as crawler:
        tasks = [crawl_and_analyze(url, crawler, pool, semaphore) for url in urls_to_process]
        await tqdm.gather(*tasks, desc="Processing Websites")
        
    print("\n[=] Pipeline execution finished.")
    await pool.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Process safely interrupted by user. All completed data is cached in PostgreSQL.")