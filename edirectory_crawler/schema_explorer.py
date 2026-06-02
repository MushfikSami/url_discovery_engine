import requests
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://admin.portal.gov.bd/api/e-directory"

def test_endpoint(endpoint_path, query_params):
    url = f"{BASE_URL}/{endpoint_path}"
    print(f"\n========================================")
    print(f"🔍 Testing: {url}")
    print(f"📦 Params: {query_params}")
    
    try:
        response = requests.get(url, params=query_params, verify=False, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract the actual data payload
            items = data.get("data", [])
            if isinstance(items, dict) and "data" in items: # Sometimes pagination wraps it twice
                items = items["data"]
                
            if items and len(items) > 0:
                first_item = items[0]
                print("\n✅ SUCCESS! Here is the complete Data Schema for 1 record:")
                print(json.dumps(first_item, indent=4, ensure_ascii=False))
                
                print("\n📋 Available Fields to Index:")
                for key in first_item.keys():
                    print(f"  - {key}")
            else:
                print("⚠️ API returned 200 OK, but the data array was empty.")
                
        else:
            print(f"⚠️ Failed: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    # Test 1: Search for an officer using the 'search_key' parameter we found
    test_endpoint("search-officers", {"search_key": "admin", "page": 1, "limit": 5})
    
    # Test 2: Get a list of officers from a specific domain (using Ministry of Public Admin domain)
    test_endpoint("officer-list", {"domain": "mopa.gov.bd", "page": 1, "limit": 5})