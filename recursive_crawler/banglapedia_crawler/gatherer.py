# gatherer.py

import aiohttp
try:
    from database import insert_pending_url
    from config import BANGLAPEDIA_LANG
except ModuleNotFoundError:
    from .database import insert_pending_url
    from .config import BANGLAPEDIA_LANG

async def gather_all_urls():
    """Uses the MediaWiki API to get every page title on Banglapedia."""
    api_url = f"https://{BANGLAPEDIA_LANG}.banglapedia.org/api.php"
    params = {
        "action": "query",
        "list": "allpages",
        "aplimit": "500", 
        "format": "json"
    }
    
    print(f"[*] Fetching all page index from Banglapedia ({BANGLAPEDIA_LANG}) API...")
    
    total_found = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(api_url, params=params) as response:
                data = await response.json()
                
                for page in data['query']['allpages']:
                    title = page['title']
                    formatted_title = title.replace(' ', '_')
                    page_url = f"https://{BANGLAPEDIA_LANG}.banglapedia.org/index.php?title={formatted_title}"
                    
                    insert_pending_url(page_url)
                    total_found += 1
                
                print(f"  -> Discovered {total_found} pages so far...")
                
                if 'continue' in data:
                    params.update(data['continue'])
                else:
                    break
                    
    print(f"[+] URL gathering complete! Processed {total_found} entries.")