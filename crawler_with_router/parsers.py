# parsers.py
import markdownify
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
import re

async def parse_with_crawl4ai(url: str) -> str:
    """
    Uses a stripped-down, headless Chromium browser to render JavaScript-heavy 
    webpages while strictly capping system resource consumption.
    """
    print(f"    [Action] Option A (JS Heavy): Routing to crawl4ai -> {url}")
    
    # 1. Strip the Browser Engine down to its absolute skeleton.
    # Consolidates threads and chokes the JavaScript V8 engine at the system layer.
    browser_cfg = BrowserConfig(
        headless=True,
        light_mode=True,  # Disables background timers and secondary extensions
        text_mode=True,   # Minimizes layout and visual pipeline layer allocations
        extra_args=[
            "--js-flags=--max-old-space-size=256",   # Hard cap: Caps JS memory footprint at 256MB
            "--disable-dev-shm-usage",               # Prevents Docker/Linux shared memory crashes
            "--disable-gpu",                         # Kills hardware graphics rendering entirely
            "--disable-software-rasterizer",         # Blocks fallback software rendering engine
            "--single-process",                      # Forces tabs to share process space if supported
            "--mute-audio",                          # Eliminates audio subsystem allocations
            "--no-sandbox"                           # Minimizes process sandboxing isolation overhead
        ]
    )
    
    # 2. Block heavy media and layouts at the request level.
    # Restricts page load timeouts to prevent infinite loops (like Cloudflare walls).
    run_cfg = CrawlerRunConfig(
        remove_overlay_elements=True,   # Drops blocking UI/modal layers automatically
        excluded_tags=[
            "nav", "footer", "header", "aside", 
            "svg", "canvas", "img", "picture", 
            "video", "audio", "iframe", "object"
        ],
        page_timeout=15000,             # 15 seconds max constraint to kill Cloudflare traps
        cache_mode=CacheMode.BYPASS     # Bypass cache safely using v0.8+ syntax
    )

    try:
        # Launch the crawler instance with the optimized configurations
        async with AsyncWebCrawler(config=browser_cfg, verbose=False) as crawler:
            result = await crawler.arun(
                url=url,
                config=run_cfg
            )
            
            if result.success and result.markdown:
                return result.markdown.strip()
            else:
                print(f"    [!] Crawl failed or returned empty content. Status: {result.status_code}")
                return ""
                
    except Exception as e:
        print(f"    [!] Crawl4AI Runtime Error: {e}")
        return ""

def parse_with_markdownify(html_content):
    """Production-grade single-pass parser using fast regex pre-stripping."""
    try:
        # Step 1: Use high-speed regex to drop massive script, style, and svg blocks 
        # BEFORE building any heavy DOM tree objects in memory.
        clean_html = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', html_content, flags=re.I)
        clean_html = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', clean_html, flags=re.I)
        clean_html = re.sub(r'<svg\b[^<]*(?:(?!<\/svg>)<[^<]*)*<\/svg>', '', clean_html, flags=re.I)
        clean_html = re.sub(r'<img\b[^>]*>', '', clean_html, flags=re.I) # Drop images entirely
        
        # Step 2: Pass the pre-shrunk text directly into markdownify in a single pass
        md = markdownify.markdownify(
            clean_html, 
            heading_style="ATX", 
            strip=['nav', 'footer', 'header', 'aside', 'script', 'style']
        )
        return md.strip()
        
    except Exception as e:
        print(f"    [!] Markdownify Error: {e}")
        return ""