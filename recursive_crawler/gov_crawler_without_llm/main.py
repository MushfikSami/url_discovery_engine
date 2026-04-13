# main.py

import asyncio
try:
    from database import setup_database
    from loader import load_urls_from_txt
    from crawler import process_pending_urls
except ModuleNotFoundError:
    from .database import setup_database
    from .loader import load_urls_from_txt
    from .crawler import process_pending_urls

async def run_pipeline():
    # 1. Ensure DB table exists
    setup_database()
    
    # 2. Load the text file into the DB queue
    load_urls_from_txt()
    
    # 3. Start crawling pending URLs
    await process_pending_urls()

if __name__ == "__main__":
    print("🚀 Starting .gov.bd Ingestion Pipeline...")
    asyncio.run(run_pipeline())