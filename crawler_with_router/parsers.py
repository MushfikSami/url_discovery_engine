# parsers.py
import markdownify
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
import re

async def parse_with_crawl4ai(url):
    """Option A: Uses a headless browser to render JS, then extracts Markdown."""
    print(f"    [Action] Option A (JS Heavy): Routing to crawl4ai -> {url}")
    try:
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(
                url=url,
                excluded_tags=["nav", "footer", "header", "aside"],
                bypass_cache=False               
            )
            if result.success:
                return result.markdown
            return ""
    except Exception as e:
        print(f"    [!] Crawl4AI Error: {e}")
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