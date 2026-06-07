import tracemalloc
import time
import markdownify
import re
import gc

def generate_heavy_html(nested_levels=50, hidden_rows=20000):
    """Generates a massive HTML string simulating a bloated expandable accordion."""
    print(f"⚙️ Generating heavy HTML payload ({hidden_rows} rows)...")
    
    html = ["<html><body>"]
    html.append("<details><summary>Click to expand massive government dataset</summary>")
    html.append("<div class='hidden-content'>")
    
    # Simulate deeply nested tags
    for _ in range(nested_levels):
        html.append("<div><span>")
        
    # Simulate massive hidden data volume
    for i in range(hidden_rows):
        html.append(f"<p>Record {i}: Important text that takes up memory.</p>")
        
    # Add junk bloat to prove regex strips it without loading DOM
    html.append("<style> .hidden-content { display: none; } body { background: #000; } </style>")
    html.append("<script> console.log('Bloat'); var hugeArray = new Array(10000); </script>")
    html.append("<svg width='1000' height='1000'><circle cx='50' cy='50' r='40' /></svg>")
    
    for _ in range(nested_levels):
        html.append("</span></div>")
        
    html.append("</div></details></body></html>")
    return "".join(html)

def parse_with_markdownify_optimized(html_content):
    """Production-grade single-pass parser using fast regex pre-stripping."""
    try:
        # 1. High-speed regex to drop massive blocks BEFORE building heavy DOM trees
        clean_html = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', html_content, flags=re.I)
        clean_html = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', clean_html, flags=re.I)
        clean_html = re.sub(r'<svg\b[^<]*(?:(?!<\/svg>)<[^<]*)*<\/svg>', '', clean_html, flags=re.I)
        clean_html = re.sub(r'<img\b[^>]*>', '', clean_html, flags=re.I)
        
        # 2. Single pass into markdownify
        md = markdownify.markdownify(
            clean_html, 
            heading_style="ATX", 
            strip=['nav', 'footer', 'header', 'aside', 'script', 'style']
        )
        return md.strip()
        
    except Exception as e:
        print(f"    [!] Markdownify Error: {e}")
        return ""

def profile_ultimate_conversion(html_payload):
    print("\n🔍 Starting Memory Profile for REGEX OPTIMIZED Markdownify...")
    
    gc.collect()
    tracemalloc.start()
    start_time = time.time()
    
    # --- ROUTING TO THE ULTIMATE FUNCTION ---
    result_markdown = parse_with_markdownify_optimized(html_payload)
    # ----------------------------------------
    
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    end_time = time.time()
    
    print("-" * 40)
    print(f"⏱️  Time taken:   {end_time - start_time:.4f} seconds")
    print(f"📈 Peak Memory:  {peak_mem / 1024 / 1024:.2f} MB")
    print(f"📊 Final Output: {len(result_markdown)} characters of Markdown")
    print("-" * 40)
    
    return result_markdown

if __name__ == "__main__":
    heavy_html = generate_heavy_html(nested_levels=50, hidden_rows=20000)
    markdown_output = profile_ultimate_conversion(heavy_html)
    
    print("\nPreview of output:")
    print(markdown_output[:200] + "...\n")