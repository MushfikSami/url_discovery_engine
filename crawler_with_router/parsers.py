# parsers.py
import markdownify
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler

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
    """Option B: Instantly converts static HTML to Markdown natively."""
    print("    [Action] Option B (Static): Routing to markdownify")
    try:
        # Pre-clean the HTML using BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        # Destroy all script and style tags completely
        for unwanted in soup(['script', 'style', 'noscript']):
            unwanted.decompose()
            
        clean_html = str(soup)
        
        md = markdownify.markdownify(
            clean_html, 
            heading_style="ATX", 
            strip=['nav', 'footer', 'header']
        )
        return md.strip()
    except Exception as e:
        print(f"    [!] Markdownify Error: {e}")
        return ""