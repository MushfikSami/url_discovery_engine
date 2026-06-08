import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import os

# The explicit directory endpoints for the top 4 levels of the BD Govt hierarchy
DIRECTORY_TARGETS = {
    "Ministries & Divisions": "https://bangladesh.gov.bd/views/ministry-and-directorate-list",
    "Departments & Agencies": "https://bangladesh.gov.bd/views/directorates-n-others",
    "Divisions": "https://bangladesh.gov.bd/views/division-list",
    "Districts": "https://bangladesh.gov.bd/views/district-list"
}

# The target file where your spider expects to find the seeds
OUTPUT_FILE = "data/crawled_alive_gov_bd_sites(_district_level).txt"

def normalize_to_root_domain(url):
    """
    Cleans a URL down to its absolute base domain and enforces HTTPS.
    Example: 'http://www.mopa.gov.bd/site/view/about' -> 'https://www.mopa.gov.bd'
    """
    try:
        if not url.startswith('http'):
            url = 'http://' + url
            
        parsed = urlparse(url)
        netloc = parsed.netloc.lower().strip()
        
        # Strip trailing slashes or ports if any sneaked in
        if not netloc or 'bangladesh.gov.bd' in netloc: 
            return None # Ignore the portal itself or invalid parsed domains
            
        # Enforce HTTPS for the modern crawler fleet
        return f"https://{netloc}"
    except Exception:
        return None

async def fetch_directory_links(client, category_name, target_url):
    print(f"📡 Fetching {category_name} from: {target_url}")
    try:
        response = await client.get(target_url, timeout=20.0, follow_redirects=True)
        soup = BeautifulSoup(response.text, 'lxml')
        
        extracted_domains = set()
        
        # Find all anchor tags that contain '.gov.bd' in their href
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            
            # We only want external links to other government portals
            if '.gov.bd' in href and not href.startswith(('mailto:', 'tel:', 'javascript:')):
                root_domain = normalize_to_root_domain(href)
                if root_domain:
                    extracted_domains.add(root_domain)
                    
        print(f"   ✅ Discovered {len(extracted_domains)} unique domains for {category_name}.")
        return extracted_domains
        
    except Exception as e:
        print(f"   ❌ Failed to fetch {category_name}: {e}")
        return set()

def save_seeds_to_txt(all_domains, filepath):
    if not all_domains:
        print("\n⚠️ No domains collected to save.")
        return

    # Ensure the target directory exists (e.g., 'data/' folder)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    # Sort them alphabetically so the text file is clean and readable
    sorted_domains = sorted(list(all_domains))

    print(f"\n💾 Saving {len(sorted_domains)} total unique seed domains to {filepath}...")
    try:
        # Overwrite the file with the fresh list
        with open(filepath, 'w') as f:
            for domain in sorted_domains:
                f.write(f"{domain}\n")
        print("🎉 Success! Text file updated.")
    except Exception as e:
        print(f"❌ Failed to write to file: {e}")

async def run_harvester():
    print("🚜 Starting Bangladesh.gov.bd Seed Harvester (District-Level Maximum)...\n")
    
    all_unique_domains = set()
    
    # Use a single async client for connection pooling
    async with httpx.AsyncClient(verify=False) as client:
        # Fetch all 4 target levels concurrently for maximum speed
        tasks = [
            fetch_directory_links(client, name, url) 
            for name, url in DIRECTORY_TARGETS.items()
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Combine the results
        for domain_set in results:
            all_unique_domains.update(domain_set)
            
    # Save the results directly to the text file
    save_seeds_to_txt(all_unique_domains, OUTPUT_FILE)
    print("\n🏁 Harvester run complete. Your fleet is ready to launch!")

if __name__ == "__main__":
    # Ensure lxml is used for fast parsing
    asyncio.run(run_harvester())