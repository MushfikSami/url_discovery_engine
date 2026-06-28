import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json

def extract_government_links(target_url):
    print(f"🚀 Fetching HTML from: {target_url}")
    
    # We use a standard User-Agent so the server doesn't block us as a bot
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Use a Set to automatically remove duplicate links
        all_links = set()
        gov_links = set()
        
        # Find all <a> tags that have an 'href' attribute
        for a_tag in soup.find_all('a', href=True):
            raw_link = a_tag['href'].strip()
            
            # urljoin ensures that relative links (e.g., "/about") become full URLs
            full_url = urljoin(target_url, raw_link)
            parsed_url = urlparse(full_url)
            
            # Keep only standard web links (ignore mailto:, javascript:, etc.)
            if parsed_url.scheme in ['http', 'https']:
                all_links.add(full_url)
                
                # Optional filtering: specifically flag .gov.bd domains
                if ".gov.bd" in parsed_url.netloc:
                    gov_links.add(full_url)

        # Convert sets back to lists for JSON serialization
        all_links = list(all_links)
        gov_links = list(gov_links)
        
        print(f"✅ Successfully extracted {len(all_links)} total unique links.")
        print(f"🇧🇩 Found {len(gov_links)} specific '.gov.bd' links.")
        
        return all_links, gov_links

    except requests.exceptions.RequestException as e:
        print(f"❌ Network Error: {e}")
        return [], []

if __name__ == "__main__":
    # The website you found
    TARGET_WEBSITE = "https://standardebooks.org/ebooks/ring-lardner/gullibles-travels/text"
    
    total_links, gov_links = extract_government_links(TARGET_WEBSITE)
    
    if total_links:
        # Save the extracted links to a JSON file for the next step (DB cross-check)
        output_data = {
            "source_url": TARGET_WEBSITE,
            "total_links_count": len(total_links),
            "gov_links_count": len(gov_links),
            "all_links": total_links,
            "gov_links": gov_links
        }
        
        output_filename = "extracted_bdgovlinks.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4)
            
        print(f"💾 Saved extracted links to '{output_filename}'")
        
        # Print a quick preview
        print("\n🔍 Preview of top 5 .gov.bd links found:")
        for link in gov_links[:5]:
            print(f"  - {link}")