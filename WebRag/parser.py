# parser.py
import requests
import tempfile
import os
from docling.document_converter import DocumentConverter
from config import WIKI_USER_AGENT

def extract_markdown_from_wiki(url: str) -> str:
    """Securely fetches HTML and uses Docling to extract Markdown."""
    if not url:
        return ""

    print(f"📄 [Secure Fetch] Downloading HTML from {url}...")
    headers = {"User-Agent": WIKI_USER_AGENT}
    
    try:
        # 1. Download the raw HTML securely
        response = requests.get(url, headers=headers, timeout=10.0)
        response.raise_for_status()
        
        # 2. Save it to a temporary file for Docling
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        print("⚙️ [Docling] Parsing local HTML into Markdown...")
        
        # 3. Parse the local file
        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        markdown_text = result.document.export_to_markdown()
        
        print(f"✅ [Docling] Successfully extracted {len(markdown_text)} characters.")
        return markdown_text
        
    except Exception as e:
        print(f"❌ [Extraction Error] Failed to process URL: {e}")
        return ""
        
    finally:
        # 4. Clean up the temp file from the server
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)