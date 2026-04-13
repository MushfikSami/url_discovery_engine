# crawler.py

import asyncio
from crawl4ai import AsyncWebCrawler
try:
    from database import get_pending_urls, update_url_status
except ModuleNotFoundError:
    from .database import get_pending_urls, update_url_status

async def process_pending_urls():
    """Fetches 'pending' URLs from Postgres and crawls them."""
    pending_urls = get_pending_urls()
    
    if not pending_urls:
        print("[*] No pending URLs to crawl. You are all caught up!")
        return

    print(f"[*] Starting crawler for {len(pending_urls)} pending pages...")
    
    async with AsyncWebCrawler(verbose=False) as crawler:
        for url in pending_urls:
            print(f"  -> Crawling: {url}")
            try:
                result = await crawler.arun(
                    url=url,
                    css_selector="#mw-content-text", 
                    word_count_threshold=15,         
                    bypass_cache=False               
                )
                
                if result.success:
                    title = url.split("title=")[-1]
                    update_url_status(url, title, result.markdown, "success")
                else:
                    update_url_status(url, "", "", "failed")
                    
            except Exception as e:
                update_url_status(url, "", "", "error")
                print(f"     [!] Error: {e}")
            
            await asyncio.sleep(0.5)