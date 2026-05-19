# search.py
import requests
from config import SEARXNG_URL

def search_wikipedia(query: str) -> str:
    """Queries SearXNG strictly using the Wikipedia engine and returns the top URL."""
    
    params = {
        "q": query,
        "engines": "wikipedia",
        "format": "json"
    }

    try:
        response = requests.get(f"{SEARXNG_URL}/search", params=params, timeout=5.0)
        response.raise_for_status()
        
        data = response.json()
        
        # 1. Try to get a standard search result first
        results = data.get("results", [])
        if results and results[0].get("url"):
            top_url = results[0].get("url")
            print(f"🔍 [SearXNG] Found Top URL (Standard Result): {top_url}")
            return top_url
            
        # 2. THE FIX: If no standard results, check if Wikipedia returned an infobox
        infoboxes = data.get("infoboxes", [])
        if infoboxes:
            # The Wikipedia URL is usually stored in the 'id' field of the infobox
            top_url = infoboxes[0].get("id") 
            if top_url and "wikipedia.org" in top_url:
                print(f"🔍 [SearXNG] Found Top URL (Infobox Match): {top_url}")
                return top_url

        print(f"⚠️ [SearXNG] No Wikipedia URLs found for: {query}")
        return None

    except requests.exceptions.RequestException as e:
        print(f"❌ [SearXNG Error] Failed to connect: {e}")
        return None