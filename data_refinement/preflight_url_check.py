import psycopg2

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

# 🎯 Topic Mapping: Defining keywords for each target service
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

def run_pre_flight_check():
    print("🔍 Initializing Pre-Flight Check on Database...\n")
    conn = psycopg2.connect(**DB_CONFIG)
    
    try:
        cursor = conn.cursor()
        
        # 1. Get the total baseline URLs
        cursor.execute("SELECT COUNT(*) FROM crawled_data;")
        total_urls = cursor.fetchone()[0]
        
        print(f"🌐 TOTAL URLs IN DATABASE: {total_urls}\n")
        print("============================================================")
        print("🗂️ ESTIMATED WORKLOAD BY TOPIC")
        print("============================================================\n")

        # 2. Breakdown by individual topics
        for topic, keywords in TOPIC_KEYWORDS.items():
            like_conditions = " OR ".join(["raw_markdown ILIKE %s" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]
            
            query = f"SELECT COUNT(*) FROM crawled_data WHERE {like_conditions};"
            cursor.execute(query, params)
            count = cursor.fetchone()[0]
            
            percentage = (count / total_urls) * 100 if total_urls > 0 else 0
            print(f"🔹 {topic:<40} : {count} URLs ({percentage:.1f}%)")

        # 3. Calculate total UNIQUE targeted URLs 
        # (Since one URL might match multiple topics, we need a distinct count)
        print("\n============================================================")
        print("🎯 FINAL TARGET CALCULATION")
        print("============================================================\n")
        
        all_keywords = []
        for kws in TOPIC_KEYWORDS.values():
            all_keywords.extend(kws)
            
        all_like_conditions = " OR ".join(["raw_markdown ILIKE %s" for _ in all_keywords])
        all_params = [f"%{kw}%" for kw in all_keywords]
        
        unique_query = f"SELECT COUNT(DISTINCT url) FROM crawled_data WHERE {all_like_conditions};"
        cursor.execute(unique_query, all_params)
        total_targeted = cursor.fetchone()[0]
        
        reduction = total_urls - total_targeted
        reduction_pct = (reduction / total_urls) * 100 if total_urls > 0 else 0
        
        print(f"✅ Total Unique Targeted URLs to Process : {total_targeted}")
        print(f"🗑️ Total Junk/Irrelevant URLs Skipped    : {reduction} (Saved {reduction_pct:.1f}% of workload!)\n")
        
        if total_targeted > 0:
            print("🚀 Your targeted fleet is perfectly configured to process only these relevant URLs.")

    except Exception as e:
        print(f"❌ Database Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    run_pre_flight_check()