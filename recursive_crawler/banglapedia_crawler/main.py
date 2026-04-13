# main.py

import asyncio
try:
    from database import setup_database
    from gatherer import gather_all_urls
    from crawler import process_pending_urls
except ModuleNotFoundError:
    from .database import setup_database
    from .gatherer import gather_all_urls
    from .crawler import process_pending_urls

async def run_pipeline():
    # 1. Ensure DB table exists
    setup_database()
    
    # 2. Gather URLs (You can comment this out if you know all URLs are already gathered)
    # await gather_all_urls()
    
    # 3. Crawl pending URLs
    await process_pending_urls()

if __name__ == "__main__":
    print("🚀 Starting Banglapedia Ingestion Pipeline...")
    asyncio.run(run_pipeline())