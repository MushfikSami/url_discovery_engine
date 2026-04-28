# extractor.py
import re
from collections import Counter

def is_javascript_heavy(soup):
    """
    Evaluates the BeautifulSoup object to determine if the page requires JS rendering.
    """
    # 1. Count the number of script tags
    script_tags = soup.find_all('script')
    
    # 2. Extract visible text
    visible_text = soup.get_text(strip=True)
    
    # Heuristic: If there is very little static text but many scripts, it's likely an SPA (React/Vue/Angular)
    if len(visible_text) < 500 and len(script_tags) > 5:
        return True
        
    # Check for common SPA root divs
    if soup.find(id=re.compile(r'^(root|app|__next)$', re.I)):
        # If the root div is completely empty, it definitely needs JS rendering
        root_div = soup.find(id=re.compile(r'^(root|app|__next)$', re.I))
        if not root_div.get_text(strip=True):
            return True

    return False

def extract_keywords(text, top_n=50):
    """Generates a list of unique keywords from the text."""
    if not text:
        return []
    
    # Keep only Bengali and English alphabets
    words = re.findall(r'[\u0980-\u09FFa-zA-Z]+', text)
    
    # Filter out tiny words (less than 3 chars)
    words = [w for w in words if len(w) > 2]
    
    # Get the most common unique words
    word_counts = Counter(words)
    top_words = [word for word, count in word_counts.most_common(top_n)]
    
    return top_words

def generate_snippet(markdown_text):
    """Creates a short snippet for Table 2, Column 3."""
    if not markdown_text:
        return ""
    
    # Clean up excess whitespace and take the first 250 characters
    clean_text = re.sub(r'\s+', ' ', markdown_text).strip()
    return clean_text[:250] + "..." if len(clean_text) > 250 else clean_text