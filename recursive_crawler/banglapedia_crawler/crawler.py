import asyncio
import re
from crawl4ai import AsyncWebCrawler
try:
    from database import get_pending_urls, update_url_status
except ModuleNotFoundError:
    from .database import get_pending_urls, update_url_status

def clean_markdown(raw_md, title):
    """
    Strips away all the Banglapedia UI bloat (headers, menus, footers) 
    from the raw markdown, leaving only the pure article text.
    """
    if not raw_md:
        return ""
        
    # 1. Find where the actual article starts.
    # The article body almost always begins with "# [Title]"
    # Example: "# আওরঙ্গজেব"
    start_marker = f"#  {title}"
    start_index = raw_md.find(start_marker)
    
    if start_index != -1:
        # Slice off everything before the title (the top menu, logo, etc.)
        cleaned_md = raw_md[start_index:]
    else:
        # Fallback: If exact title isn't found, try finding the first H1 tag
        h1_match = re.search(r"^#\s+.*", raw_md, re.MULTILINE)
        if h1_match:
            cleaned_md = raw_md[h1_match.start():]
        else:
            cleaned_md = raw_md

    # 2. Find where the actual article ends.
    # The footer usually starts with the source link like:
    # '[http://bn.banglapedia.org/index.php?...' 
    # or 'লুকানো বিষয়শ্রেণী:' (Hidden Categories)
    
    end_marker_1 = "'[http"
    end_marker_2 = "লুকানো বিষয়শ্রেণী:"
    
    end_index_1 = cleaned_md.find(end_marker_1)
    end_index_2 = cleaned_md.find(end_marker_2)
    
    # Use whichever footer marker comes first
    valid_ends = [idx for idx in [end_index_1, end_index_2] if idx != -1]
    
    if valid_ends:
        final_end_index = min(valid_ends)
        # Slice off everything after the article ends
        cleaned_md = cleaned_md[:final_end_index].strip()
        
    return cleaned_md

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
                    # We can go back to the standard selector now
                    css_selector="#mw-content-text", 
                    word_count_threshold=15,         
                    bypass_cache=True               
                )
                
                if result.success:
                    # Clean up the URL to get the readable title
                    import urllib.parse
                    raw_title = url.split("title=")[-1]
                    decoded_title = urllib.parse.unquote(raw_title).replace('_', ' ')
                    
                    # Pass the raw markdown through our new cleaner function
                    pure_markdown = clean_markdown(result.markdown, decoded_title)
                    
                    update_url_status(url, decoded_title, pure_markdown, "success")
                else:
                    update_url_status(url, "", "", "failed")
                    
            except Exception as e:
                update_url_status(url, "", "", "error")
                print(f"     [!] Error: {e}")
            
            await asyncio.sleep(0.5)