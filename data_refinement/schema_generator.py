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

# Set this based on your VRAM overhead. 
# 5 is a very safe starting point for a high-tier local GPU environment.
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

# ==========================================
# 2. DATABASE RETRIEVAL
# ==========================================
def get_crawled_markdown_for_service(service_name):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cursor = conn.cursor()
        search_term = f"%{service_name}%"
        cursor.execute("""
            SELECT raw_markdown FROM crawled_data 
            WHERE raw_markdown ILIKE %s 
            LIMIT 5;
        """, (search_term,))
        
        results = cursor.fetchall()
        if not results:
            return ""
            
        combined_md = "\n\n".join([row[0] for row in results])
        return combined_md[:12000] # Safe context limit
        
    except Exception as e:
        return ""
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 3. LLM GENERATION WITH VLLM
# ==========================================
def generate_missing_tiers(category, sub_category, service, existing_topics, raw_markdown):
    system_prompt = """You are a top-tier Data Architect for the Bangladesh Government Chatbot.
Your job is to structure raw government text into a strict 5-Tier Schema:
Tier 1: Core Definition & Eligibility (What/Who)
Tier 2: Procedural Logistics (How/Where/When)
Tier 3: Financial Logistics (Cost/Fees)
Tier 4: Modifications & Renewals (Updates/Corrections)
Tier 5: Troubleshooting & Support (Why rejected/Lost/Helpline)

RULES:
1. Output MUST be in valid JSON array format.
2. The language MUST be in Bengali.
3. Formulate the "Topic" as a natural user question.
4. DO NOT duplicate information that is already provided in the "Existing Data". ONLY generate questions for the missing tiers based on the "Source Markdown".
"""

    user_prompt = f"""
Service Name: {service}
Category: {category} -> {sub_category}

EXISTING DATA COVERAGE (Do NOT generate these again):
{existing_topics}

SOURCE MARKDOWN FROM CRAWLER:
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
            temperature=0.3, 
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
    """The self-contained task that the ThreadPoolExecutor runs concurrently."""
    raw_md = get_crawled_markdown_for_service(service)
    
    if not raw_md.strip():
        return service, [] # No crawled data found
        
    generated_json = generate_missing_tiers(category, sub_category, service, existing_topics, raw_md)
    
    new_rows = []
    for item in generated_json:
        new_rows.append({
            'Category': category,
            'Sub-Category': sub_category,
            'Service': service,
            'Alternate Variants': '',
            'Keyword': item.get('Keyword', ''),
            'Passage ID': f"GEN-{int(time.time())}", 
            'Topic': f"[{item.get('Tier', 'Tier X')}] {item.get('Topic', '')}",
            'Text': item.get('Text', ''),
            'Text Keywords': item.get('Keyword', ''),
            'URL': 'Generated via Crawler DB'
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
    
    # If this is the very first run, create the baseline output CSV
    if not os.path.exists(OUTPUT_CSV):
        df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        print("💾 Baseline output file created.")

    grouped = df.groupby(['Category', 'Sub-Category', 'Service'])
    
    # Filter out services we've already completed
    pending_tasks = []
    for (category, sub_category, service), group in grouped:
        if service not in processed_services:
            existing_topics = "\n".join(group['Topic'].tolist())
            pending_tasks.append((category, sub_category, service, existing_topics))
            
    print(f"📊 Total Services: {len(grouped)} | Already Done: {len(processed_services)} | Pending: {len(pending_tasks)}")
    
    if not pending_tasks:
        print("✅ All services have already been processed! Pipeline complete.")
        return

    # Launch the parallel fleet
    print(f"⚡ Launching {CONCURRENT_WORKERS} concurrent vLLM streams...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        # Submit all tasks to the queue
        future_to_service = {
            executor.submit(process_single_service, cat, subcat, srv, top): srv 
            for (cat, subcat, srv, top) in pending_tasks
        }
        
        # Process results exactly as they finish
        for future in tqdm(as_completed(future_to_service), total=len(pending_tasks), desc="Processing Services"):
            service_name, generated_rows = future.result()
            
            # 1. If rows were generated, safely append them to the CSV immediately
            if generated_rows:
                new_df = pd.DataFrame(generated_rows)
                # mode='a' appends to the file, header=False prevents writing the column names again
                new_df.to_csv(OUTPUT_CSV, mode='a', header=False, index=False, encoding='utf-8-sig')
                
            # 2. Mark the service as complete in the checkpoint file
            with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
                f.write(f"{service_name}\n")

    print(f"\n🎉 Pipeline Execution Complete! All data secured in {OUTPUT_CSV}.")

if __name__ == "__main__":
    run_pipeline()