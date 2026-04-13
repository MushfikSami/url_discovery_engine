# crawler.py

import asyncio
import re
from crawl4ai import AsyncWebCrawler
try:
    from database import get_pending_urls, update_url_status
except ModuleNotFoundError:
    from .database import get_pending_urls, update_url_status

def clean_gov_bd_markdown(raw_md, title=""):
    """
    Strips away standard a2i framework bloat from Bangladesh gov websites.
    """
    if not raw_md:
        return ""
        
    lines = raw_md.split('\n')
    cleaned_lines = []
    
    junk_keywords = [
        "অফিসের ধরণ নির্বাচন করুন",
        "এক্সেসিবিলিটি মেনুতে যান",
        "বাংলাদেশ জাতীয় তথ্য বাতায়ন",
        "অফিস স্তর নির্বাচন করুন",
        "বিভাগ নির্বাচন করুন",
        "জেলা নির্বাচন করুন",
        "উপজেলা নির্বাচন করুন",
        "হটলাইন",
        "মেনু নির্বাচন করুন",
        "জরুরি সেবা নম্বরসমূহ",
        "ফন্ট বৃদ্ধি ফন্ট হ্রাস",
        "স্ক্রিন রিডার ডাউনলোড করুন",
        "© 2026 সর্বস্বত্ব সংরক্ষিত",
        "পরিকল্পনা এবং বাস্তবায়ন"
    ]
    
    for line in lines:
        line_stripped = line.strip()
        
        # Stop processing if we hit the standard footer
        if "© 2026 সর্বস্বত্ব সংরক্ষিত" in line_stripped or "জরুরি সেবা নম্বরসমূহ" in line_stripped:
            break
            
        is_junk = any(keyword in line_stripped for keyword in junk_keywords)
        
        if is_junk:
            continue
            
        cleaned_lines.append(line)

    final_md = "\n".join(cleaned_lines)
    final_md = re.sub(r'\n{3,}', '\n\n', final_md)
    
    return final_md.strip()

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
                    excluded_tags=["nav", "footer", "header", "aside", "form", "script", "style", "noscript"],
                    word_count_threshold=20,         
                    bypass_cache=False               
                )
                
                if result.success:
                    title = getattr(result, 'title', url) 
                    clean_md = clean_gov_bd_markdown(result.markdown, title)
                    update_url_status(url, title, clean_md, "success")
                else:
                    update_url_status(url, "", "", "failed")
                    
            except Exception as e:
                update_url_status(url, "", "", "error")
                print(f"     [!] Error: {e}")
            
            await asyncio.sleep(0.5)