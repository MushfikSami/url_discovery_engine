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

def monitor_crawled_pdfs():
    print("🔍 Connecting to database to monitor OCR PDF & Gazette counts...\n")
    conn = psycopg2.connect(**DB_CONFIG)
    
    try:
        cursor = conn.cursor()
        
        # 1. সর্বমোট কতগুলো PDF OCR হয়েছে তার কাউন্ট বের করা
        cursor.execute("""
            SELECT COUNT(*) 
            FROM crawled_data 
            WHERE raw_markdown LIKE '%%[OCR EXTRACTED FROM ATTACHED PDF]%%';
        """)
        total_ocr_pdfs = cursor.fetchone()[0]
        
        print(f"📊 TOTAL PDFs SUCCESSFULLY OCR'd IN DB: {total_ocr_pdfs}\n")
        
        print("==================================================================================")
        print(f"{'CATEGORY / TOPIC':<38} | {'TOTAL PDFs':<12} | {'GAZETTE PDFs':<12}")
        print("==================================================================================")
        
        # 2. প্রতিটি টপিকের জন্য আলাদাভাবে কাউন্ট এবং গেজেট কাউন্ট বের করা
        for topic, keywords in TOPIC_KEYWORDS.items():
            like_conditions = " OR ".join([f"raw_markdown ILIKE %s" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]
            
            # 🛠️ UPDATE: CASE WHEN ব্যবহার করে একই কোয়েরিতে গেজেটের সংখ্যা বের করা হয়েছে
            query = f"""
                SELECT 
                    COUNT(url) AS total_pdfs,
                    COALESCE(SUM(CASE WHEN raw_markdown ILIKE '%%বাংলাদেশ গেজেট%%' THEN 1 ELSE 0 END), 0) AS gazette_pdfs
                FROM crawled_data 
                WHERE raw_markdown LIKE '%%[OCR EXTRACTED FROM ATTACHED PDF]%%'
                AND ({like_conditions});
            """
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            
            count = result[0]
            gazette_count = int(result[1])
            
            if count > 0:
                print(f"✅ {topic:<36} | {count:<12} | {gazette_count:<12}")
            else:
                print(f"⏳ {topic:<36} | {count:<12} | {gazette_count:<12}")
                
        print("==================================================================================\n")
        print("🚀 Monitoring complete. Run this script anytime to check progress.")
        
    except Exception as e:
        print(f"❌ Database Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    monitor_crawled_pdfs()