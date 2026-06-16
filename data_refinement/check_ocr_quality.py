import psycopg2
from docx import Document
from docx.shared import Pt
import os

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

def generate_docx():
    print("📝 Initializing Document Generator...")
    doc = Document()
    
    # Add a main title to the document
    title = doc.add_heading('Gov Spider - OCR Quality Assurance Samples', 0)
    doc.add_paragraph("This document contains full OCR extractions from 3 random PDFs per service category for data quality review.\n")
    
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cursor = conn.cursor()
        
        for topic, keywords in TOPIC_KEYWORDS.items():
            print(f"🔍 Fetching up to 3 samples for: {topic}...")
            
            like_conditions = " OR ".join([f"raw_markdown ILIKE %s" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]
            
            # Fetch exactly 3 random samples
            query = f"""
                SELECT url, raw_markdown 
                FROM crawled_data 
                WHERE raw_markdown LIKE '%%[OCR EXTRACTED FROM ATTACHED PDF]%%'
                AND ({like_conditions})
                ORDER BY RANDOM()
                LIMIT 3;
            """
            
            cursor.execute(query, params)
            samples = cursor.fetchall()
            
            if not samples:
                print(f"   ⏳ Skipping {topic} (No data yet)")
                continue
                
            # Add Topic Heading
            doc.add_heading(f'📌 Category: {topic}', level=1)
            
            for i, (url, markdown) in enumerate(samples):
                doc.add_heading(f'Sample {i+1}', level=2)
                doc.add_paragraph(f"🔗 Source URL: {url}", style='Intense Quote')
                
                try:
                    # Extract the OCR part to hide raw HTML markdown
                    ocr_segment = markdown.split("[OCR EXTRACTED FROM ATTACHED PDF] ###")[1].strip()
                    
                    # Add the text paragraph by paragraph to maintain structure
                    for line in ocr_segment.split('\n'):
                        if line.strip():
                            doc.add_paragraph(line.strip())
                            
                except Exception as e:
                    doc.add_paragraph(f"[Error parsing OCR segment: {e}]")
                
                doc.add_paragraph("\n" + "="*50 + "\n")
                
            doc.add_page_break() # Keep each category's samples separated nicely
            
        output_file = "OCR_Quality_Samples.docx"
        doc.save(output_file)
        print(f"\n✅ Success! Saved all samples to: '{output_file}'")
        print("📥 You can now download this file from your server to share with the Data Team.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    generate_docx()