# search.py
import requests
import re
from config import WIKI_USER_AGENT

def is_bengali(text: str) -> bool:
    """Detects if the query contains Bengali characters."""
    return bool(re.search(r'[\u0980-\u09FF]', text))

def search_mediawiki(query: str):
    """
    Queries the official MediaWiki OpenSearch API.
    Returns the top URL and a list of alternate suggestions.
    """
    # Auto-route to the correct language database
    lang = "bn" if is_bengali(query) else "en"
    url = f"https://{lang}.wikipedia.org/w/api.php"

    params = {
        "action": "opensearch",
        "search": query,
        "limit": 3,           # Fetch top 3 suggestions
        "namespace": 0,       # Only search standard articles
        "format": "json"
    }
    
    headers = {
        "User-Agent": WIKI_USER_AGENT
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5.0)
        response.raise_for_status()
        
        # OpenSearch format: [ "Query", ["Title1", "Title2"], ["Desc1", "Desc2"], ["URL1", "URL2"] ]
        data = response.json()
        titles = data[1]
        urls = data[3]
        
        if not urls:
            print(f"⚠️ [MediaWiki] No results found for: {query}")
            return None, []
            
        top_url = urls[0]
        suggestions = titles[1:] # Keep the 2nd and 3rd titles as alternatives
        
        print(f"🔍 [MediaWiki] Top Match: {top_url}")
        if suggestions:
            print(f"💡 [MediaWiki] Did you mean? {', '.join(suggestions)}")
            
        return top_url, suggestions

    except requests.exceptions.RequestException as e:
        print(f"❌ [MediaWiki Error] API failed: {e}")
        return None, []