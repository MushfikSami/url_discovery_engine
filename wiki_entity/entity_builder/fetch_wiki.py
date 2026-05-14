import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_resilient_session():
    """Shared session with built-in retry logic for all threads."""
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session

# Global connection pool
session = get_resilient_session()

def process_single_category(category_name, current_depth):
    """Worker function: Fetches a single category, handling all pagination."""
    endpoint = "https://bn.wikipedia.org/w/api.php"
    headers = {'User-Agent': 'BDEntityCrawlerBot/3.0 (Threaded Level-Traversal)'}
    
    subcategories = []
    articles = []
    continue_params = {} # Required to get past the 500-item limit
    
    while True:
        params = {
            "action": "query",
            "generator": "categorymembers",
            "gcmtitle": category_name,
            "gcmlimit": "max",
            "prop": "pageprops",
            "ppprop": "wikibase_item",
            "format": "json"
        }
        params.update(continue_params) # Add the 'next page' tokens if they exist
        
        try:
            response = session.get(endpoint, headers=headers, params=params, timeout=30)
            
            if response.status_code != 200:
                print(f"   ⚠️ API Blocked {category_name} (Code: {response.status_code})")
                break
                
            data = response.json()
            
            if "query" in data and "pages" in data["query"]:
                for page_info in data["query"]["pages"].values():
                    title = page_info["title"]
                    
                    if title.startswith("বিষয়শ্রেণী:"): 
                        subcategories.append(title)
                    elif not title.startswith("টেমপ্লেট:") and not title.startswith("উইকিপিডিয়া:"):
                        if "pageprops" in page_info and "wikibase_item" in page_info["pageprops"]:
                            articles.append({
                                "Wikidata_ID": page_info["pageprops"]["wikibase_item"],
                                "Bangla_Wikipedia_Title": title,
                                "Wikipedia_URL": f"https://bn.wikipedia.org/wiki/{title.replace(' ', '_')}",
                                "Category_Discovered_In": category_name,
                                "Depth": current_depth
                            })
            
            # Check if there is another page of data in this category
            if "continue" in data:
                continue_params = data["continue"]
            else:
                break # No more pages, exit the while loop
                
        except Exception as e:
            print(f"   ⚠️ Thread Error on {category_name}: {e}")
            break
            
    # A tiny polite pause so the 5 workers don't fire at the exact same millisecond
    time.sleep(0.3) 
    return subcategories, articles

def run_threaded_crawler(base_category, max_depth=3, max_workers=5):
    print(f"🚀 Launching Threaded Crawler ({max_workers} Workers) at '{base_category}'\n")
    start_time = time.time()
    
    visited_categories = set([base_category])
    current_level_categories = [base_category]
    all_extracted_articles = []
    
    for depth in range(max_depth + 1):
        if not current_level_categories:
            break
            
        print(f"========== 📂 STARTING DEPTH {depth} ({len(current_level_categories)} folders to scan) ==========")
        next_level_categories = set()
        
        # Spin up the Thread Pool for the current level
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Map the categories to the workers
            future_to_cat = {
                executor.submit(process_single_category, cat, depth): cat 
                for cat in current_level_categories
            }
            
            # Process results as soon as a worker finishes a folder
            completed = 0
            for future in as_completed(future_to_cat):
                cat = future_to_cat[future]
                try:
                    new_subcats, new_articles = future.result()
                    
                    # Store the articles
                    all_extracted_articles.extend(new_articles)
                    
                    # Queue up the subcategories for the NEXT depth loop
                    for subcat in new_subcats:
                        if subcat not in visited_categories:
                            visited_categories.add(subcat)
                            next_level_categories.add(subcat)
                            
                    completed += 1
                    if completed % 50 == 0:
                        print(f"   ... Processed {completed}/{len(current_level_categories)} folders at Depth {depth}")
                        
                except Exception as exc:
                    print(f"   ❌ {cat} generated an exception: {exc}")
                    
        # Set up the folders for the next depth
        current_level_categories = list(next_level_categories)

    # Wrap up and save
    df = pd.DataFrame(all_extracted_articles)
    if not df.empty:
        df = df.drop_duplicates(subset=['Wikidata_ID'])
        output_file = "bangladesh_bn_wiki_true_massive.csv"
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        print("\n" + "="*50)
        print(f"✅ CRAWL COMPLETE in {time.time() - start_time:.2f} seconds!")
        print(f"💾 Saved {len(df)} unique Wikipedia Articles & Q-IDs to CSV.")
        print("="*50)
    else:
        print("❌ Crawler failed to find any articles.")

if __name__ == "__main__":
    # 5 workers is the absolute limit for safety. 
    run_threaded_crawler("বিষয়শ্রেণী:বাংলাদেশ", max_depth=3, max_workers=5)