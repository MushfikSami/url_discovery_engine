# parser.py
from docling.document_converter import DocumentConverter

def extract_markdown_from_url(url: str) -> str:
    """Uses IBM Docling to scrape a URL and convert it to clean Markdown."""
    if not url:
        return ""

    print(f"📄 [Docling] Parsing and converting {url} into Markdown...")
    
    try:
        converter = DocumentConverter()
        result = converter.convert(url)
        
        # Export the parsed document tree to Markdown
        markdown_text = result.document.export_to_markdown()
        
        print(f"✅ [Docling] Successfully extracted {len(markdown_text)} characters.")
        return markdown_text
        
    except Exception as e:
        print(f"❌ [Docling Error] Failed to parse URL: {e}")
        return ""