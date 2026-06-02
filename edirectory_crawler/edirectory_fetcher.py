import requests
import urllib3
import json

# Suppress the insecure request warnings since we are intentionally bypassing SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_all_ministries():
    url = "https://admin.portal.gov.bd/api/e-directory/all-ministry"
    print(f"🚀 Fetching data from: {url}")
    
    try:
        # verify=False ignores the local issuer certificate error
        response = requests.get(url, verify=False, timeout=15)
        
        if response.status_code == 200:
            print("✅ HTTP 200 OK: Successfully connected to the API!")
            
            # Parse the JSON response
            json_payload = response.json()
            ministries = json_payload.get("data", [])
            
            # Save the raw JSON to a file for your indexing pipeline
            output_file = "bd_ministries_clean.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(json_payload, f, indent=4, ensure_ascii=False)
                
            print(f"💾 Saved {len(ministries)} ministry records to '{output_file}'")
            
            # Print a quick preview of the extracted data
            print("\n📊 Data Preview:")
            for index, min_data in enumerate(ministries[:5]):
                en_name = min_data.get("sitename_en", "N/A")
                bn_name = min_data.get("sitename_bn", "N/A")
                subdomain = min_data.get("subdomain", "N/A")
                print(f"  {index + 1}. {en_name} | {bn_name} | {subdomain}")
            print("  ... and more!")
            
        else:
            print(f"⚠️ Failed with HTTP Status Code: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Network Error: {e}")

if __name__ == "__main__":
    fetch_all_ministries()