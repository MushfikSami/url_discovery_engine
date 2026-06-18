import psycopg2
import os
import re
import hashlib
from tqdm import tqdm

# ==========================================
# CONFIGURATION
# ==========================================
DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

TOPIC_KEYWORDS = {
    "জাতীয় পরিচয়পত্র (NID)": ["জাতীয় পরিচয়পত্র", "এনআইডি", "NID", "পরিচয়পত্র"],
    "জন্ম ও মৃত্যু নিবন্ধন (Birth/Death)": ["জন্ম নিবন্ধন", "মৃত্যু নিবন্ধন", "জন্ম সনদ", "মৃত্যু সনদ"],
    "ট্রেড লাইসেন্স (Trade License)": ["ট্রেড লাইসেন্স", "Trade License"],
    "ভূমি সেবা (Land Services)": ["ভূমি সেবা", "খতিয়ান", "পর্চা", "নামজারি", "ভূমি কর", "ই-নামজারি"],
    "পাসপোর্ট (Passport)": ["পাসপোর্ট", "Passport", "ই-পাসপোর্ট", "e-passport"],
    "যানবাহন ও লাইসেন্স (Vehicle/License)": ["ড্রাইভিং লাইসেন্স", "যানবাহন নিবন্ধন", "বিআরটিএ", "BRTA", "রুট পারমিট"],
    "ইউটিলিটি বিল (Utility Bills)": ["বিদ্যুৎ বিল", "গ্যাস বিল", "পানি বিল", "ডেসকো", "ডিপিডিসি", "ওয়াসা", "তিতাস"],
    "স্বাস্থ্য সেবা (Health Services)": ["স্বাস্থ্য সেবা", "হাসপাতাল", "চিকিৎসা", "স্বাস্থ্য অধিদপ্তর", "DGHS", "DGDA"]
}

BASE_DIR = "Extracted_Gazettes"

def generate_safe_filename(url):
    """Creates a short, safe filename from a URL to prevent OS errors."""
    # Take the last part of the URL (e.g., the file name)
    base_name = url.split('/')[-1]
    # Remove any weird characters
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', base_name)[:30]
    # Add a short hash of the full URL to guarantee uniqueness
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:6]
    return f"gazette_{safe_name}_{url_hash}.md"

def extract_and_save_gazettes():
    print("🚀 Initializing Gazette Extraction Pipeline...\n")
    
    # Create the base directory
    os.makedirs(BASE_DIR, exist_ok=True)
    
    conn = psycopg2.connect(**DB_CONFIG)
    total_saved = 0
    
    try:
        cursor = conn.cursor()
        
        for topic, keywords in TOPIC_KEYWORDS.items():
            # Sanitize topic name for folder creation (e.g., replace '/' with '_')
            safe_folder_name = topic.replace("/", "_")
            topic_dir = os.path.join(BASE_DIR, safe_folder_name)
            
            # Build the query
            like_conditions = " OR ".join([f"raw_markdown ILIKE %s" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]
            
            query = f"""
                SELECT url, raw_markdown 
                FROM crawled_data 
                WHERE raw_markdown LIKE '%%[OCR EXTRACTED FROM ATTACHED PDF]%%'
                AND raw_markdown ILIKE '%%বাংলাদেশ গেজেট%%'
                AND ({like_conditions});
            """
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            if not results:
                print(f"⏳ {topic:<38} | 0 Gazettes found.")
                continue
                
            # Create the folder only if we found gazettes for this topic
            os.makedirs(topic_dir, exist_ok=True)
            print(f"📂 {topic:<38} | Extracting {len(results)} Gazettes...")
            
            # Save each gazette
            for url, markdown in tqdm(results, desc=f"   Saving", leave=False):
                try:
                    # ✂️ Slice out ONLY the OCR text, dropping the web HTML
                    ocr_segment = markdown.split("### [OCR EXTRACTED FROM ATTACHED PDF] ###")[-1].strip()
                    
                    filename = generate_safe_filename(url)
                    filepath = os.path.join(topic_dir, filename)
                    
                    # Write to file
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Source URL: {url}\n")
                        f.write("=" * 80 + "\n\n")
                        f.write(ocr_segment)
                        
                    total_saved += 1
                except Exception as e:
                    pass # Silently skip if there's a weird parsing error on a specific row
                    
    except Exception as e:
        print(f"❌ Database Error: {e}")
    finally:
        conn.close()
        
    print("\n" + "="*60)
    print(f"🎉 EXTRACTION COMPLETE! Successfully saved {total_saved} Gazette files.")
    print(f"📁 All files are located in the '{BASE_DIR}' folder.")
    print("="*60)

if __name__ == "__main__":
    extract_and_save_gazettes()