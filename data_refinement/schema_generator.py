import pandas as pd
import psycopg2
import json
import time
import os
from openai import OpenAI
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. CONFIGURATION & VLLM SETUP
# ==========================================
VLLM_API_BASE = "http://localhost:5000/v1" 
VLLM_API_KEY = "no_key"  
MODEL_NAME = "qwen36"  

CONCURRENT_WORKERS = 5 

client = OpenAI(
    api_key=VLLM_API_KEY,
    base_url=VLLM_API_BASE,
)

DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

INPUT_CSV = "incomplete_data_v7.csv"
OUTPUT_CSV = "Master_Dataset_Enhanced.csv"
CHECKPOINT_FILE = "data/generator_checkpoint.txt"

# Targeted Categories and their high-value keywords
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

# ==========================================
# 2. AUTHORITATIVE DATABASE RETRIEVAL
# ==========================================
def get_authoritative_markdown(service_name, category):
    """
    Tiered retrieval: 
    1. Looks for OCR/Gazette matching the specific Service.
    2. Fallback to OCR/Gazette matching the Category Keywords.
    3. Fallback to Standard HTML.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    combined_md = ""
    try:
        cursor = conn.cursor()
        
        # Tags for high-authority documents
        ocr_tag = '%[OCR EXTRACTED FROM ATTACHED PDF]%'
        gazette_tag = '%বাংলাদেশ গেজেট%'
        
        # --- TIER 1: Exact Service Match inside a PDF/Gazette ---
        cursor.execute("""
            SELECT raw_markdown FROM crawled_data 
            WHERE (raw_markdown LIKE %s OR raw_markdown LIKE %s)
            AND raw_markdown ILIKE %s 
            LIMIT 5;
        """, (ocr_tag, gazette_tag, f"%{service_name}%"))
        
        results = cursor.fetchall()
        
        # --- TIER 2: Keyword Match inside a PDF/Gazette ---
        if not results:
            # Find the matching keyword list for the category (if it exists)
            cat_keys = []
            for key, words in TOPIC_KEYWORDS.items():
                if key in category or category in key:
                    cat_keys = words
                    break
            
            if cat_keys:
                # Search using the first two major keywords of the category
                like_conditions = " OR ".join(["raw_markdown ILIKE %s" for _ in cat_keys[:2]])
                params = [ocr_tag, gazette_tag] + [f"%{kw}%" for kw in cat_keys[:2]]
                
                query = f"""
                    SELECT raw_markdown FROM crawled_data 
                    WHERE (raw_markdown LIKE %s OR raw_markdown LIKE %s)
                    AND ({like_conditions})
                    LIMIT 5;
                """
                cursor.execute(query, params)
                results = cursor.fetchall()

        # --- TIER 3: Standard HTML Fallback ---
        if not results:
            cursor.execute("""
                SELECT raw_markdown FROM crawled_data 
                WHERE raw_markdown ILIKE %s 
                LIMIT 3;
            """, (f"%{service_name}%",))
            results = cursor.fetchall()

        if results:
            combined_md = "\n\n".join([row[0] for row in results])
            return combined_md[:15000] # Increased context limit for heavy PDFs
            
        return ""
        
    except Exception as e:
        print(f"DB Error: {e}")
        return ""
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 3. LLM GENERATION WITH VLLM
# ==========================================
def generate_missing_tiers(category, sub_category, service, existing_topics, raw_markdown):
    system_prompt = """You are a top-tier Data Architect and Legal Analyst for the Bangladesh Government Chatbot.
Your job is to structure raw official text (specifically Bangladesh Gazettes and OCR'd Government PDFs) into a strict 5-Tier Schema:

Tier 1: Core Definition & Eligibility (What/Who)
Tier 2: Procedural Logistics (How/Where/When)
Tier 3: Financial Logistics (Cost/Fees/Taxes)
Tier 4: Modifications & Renewals (Updates/Corrections)
Tier 5: Troubleshooting & Support (Why rejected/Lost/Helpline)

RULES:
1. Output MUST be in valid JSON array format.
2. The language MUST be in precise, formal Bengali.
3. Formulate the "Topic" as a natural user question.
4. Extract EXACT fees, dates, and clause numbers if present in the document.
5. DO NOT duplicate information that is already provided in the "Existing Data". 
6. ONLY generate questions for the missing tiers based on the "Source Markdown".
"""

    user_prompt = f"""
Service Name: {service}
Category: {category} -> {sub_category}

EXISTING DATA COVERAGE (Do NOT generate these again):
{existing_topics}

AUTHORITATIVE SOURCE MARKDOWN (Gazette/PDF):
{raw_markdown}

TASK: 
Generate the MISSING schema tiers as a JSON list of dictionaries.
Keys required: "Tier", "Topic", "Text", "Keyword".
"""

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2, # Lowered temperature for factual legal extraction
            max_tokens=2048
        )
        
        raw_output = response.choices[0].message.content.strip()
        
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3]
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3]
            
        return json.loads(raw_output)
        
    except Exception:
        return []

# ==========================================
# 4. WORKER THREAD LOGIC
# ==========================================
def process_single_service(category, sub_category, service, existing_topics):
    raw_md = get_authoritative_markdown(service, category)
    
    if not raw_md.strip():
        return service, [] 
        
    generated_json = generate_missing_tiers(category, sub_category, service, existing_topics, raw_md)
    
    new_rows = []
    for item in generated_json:
        new_rows.append({
            'Category': category,
            'Sub-Category': sub_category,
            'Service': service,
            'Alternate Variants': '',
            'Keyword': item.get('Keyword', ''),
            'Passage ID': f"GEN-AUTH-{int(time.time())}", 
            'Topic': f"[{item.get('Tier', 'Tier X')}] {item.get('Topic', '')}",
            'Text': item.get('Text', ''),
            'Text Keywords': item.get('Keyword', ''),
            'URL': 'Generated via Official PDF/Gazette OCR'
        })
        
    return service, new_rows

# ==========================================
# 5. ORCHESTRATOR & CHECKPOINT MANAGER
# ==========================================
def run_pipeline():
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    
    print("🚀 Initializing Checkpoint System...")
    processed_services = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            processed_services = set(line.strip() for line in f)
    
    print("🚀 Loading existing dataset...")
    df = pd.read_csv(INPUT_CSV)
    df['Service'] = df['Service'].fillna('Unknown Service')
    df['Topic'] = df['Topic'].fillna('Unknown Topic')
    
    if not os.path.exists(OUTPUT_CSV):
        df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        print("💾 Baseline output file created.")

    grouped = df.groupby(['Category', 'Sub-Category', 'Service'])
    
    pending_tasks = []
    for (category, sub_category, service), group in grouped:
        if service not in processed_services:
            existing_topics = "\n".join(group['Topic'].tolist())
            pending_tasks.append((category, sub_category, service, existing_topics))
            
    print(f"📊 Total Services: {len(grouped)} | Already Done: {len(processed_services)} | Pending: {len(pending_tasks)}")
    
    if not pending_tasks:
        print("✅ All services have already been processed! Pipeline complete.")
        return

    print(f"⚡ Launching {CONCURRENT_WORKERS} concurrent vLLM streams targeting PDF/Gazettes...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        future_to_service = {
            executor.submit(process_single_service, cat, subcat, srv, top): srv 
            for (cat, subcat, srv, top) in pending_tasks
        }
        
        for future in tqdm(as_completed(future_to_service), total=len(pending_tasks), desc="Processing Services"):
            service_name, generated_rows = future.result()
            
            if generated_rows:
                new_df = pd.DataFrame(generated_rows)
                new_df.to_csv(OUTPUT_CSV, mode='a', header=False, index=False, encoding='utf-8-sig')
                
            with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
                f.write(f"{service_name}\n")

    print(f"\n🎉 Pipeline Execution Complete! Authoritative dataset secured in {OUTPUT_CSV}.")

if __name__ == "__main__":
    run_pipeline()