import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pdf2image import convert_from_bytes
import base64
import io
import os
import gc
import psycopg2
from tqdm import tqdm
from openai import AsyncOpenAI

# ==========================================
# 1. CONFIGURATION
# ==========================================
VLLM_API_BASE = "http://localhost:5000/v1" 
VLLM_API_KEY = "no-key"  
MODEL_NAME = "qwen36"   

DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

CHECKPOINT_FILE = "data/vision_checkpoint.txt"
MAX_PAGES_PER_PDF = 30 
NUM_NETWORK_WORKERS = 50
NUM_GPU_WORKERS = 2

client = AsyncOpenAI(api_key=VLLM_API_KEY, base_url=VLLM_API_BASE)

# Global progress bar tracking total pending URLs
pbar = None

# 🎯 NEW: Topic Mapping to restrict the fleet to valuable data only
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
# 2. DATABASE HELPERS
# ==========================================
def fetch_all_crawled_urls():
    """Fetches ONLY the URLs that contain the specified topic keywords in their markdown."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cursor = conn.cursor()
        
        # Flatten all keywords into a single list
        all_keywords = []
        for kws in TOPIC_KEYWORDS.values():
            all_keywords.extend(kws)
            
        # Build the dynamic SQL conditions for ILIKE matching
        like_conditions = " OR ".join(["raw_markdown ILIKE %s" for _ in all_keywords])
        params = [f"%{kw}%" for kw in all_keywords]
        
        # Execute query to filter at the database level
        query = f"SELECT url FROM crawled_data WHERE {like_conditions};"
        cursor.execute(query, params)
        
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

def append_to_markdown_sync(url, new_text):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE crawled_data 
            SET raw_markdown = COALESCE(raw_markdown, '') || %s 
            WHERE url = %s;
                """, (f"\n\n### [OCR EXTRACTED FROM ATTACHED PDF] ###\n{new_text}\n", url))
        conn.commit()
    finally:
        conn.close()

async def append_to_markdown(url, new_text):
    await asyncio.to_thread(append_to_markdown_sync, url, new_text)

# ==========================================
# 3. VISION LLM PIPELINE
# ==========================================
def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85)
    out = base64.b64encode(buffered.getvalue()).decode('utf-8')
    buffered.close()
    return out

async def perform_ocr(base64_image):
    system_prompt = "You are an expert OCR system. Extract all text from this image exactly as it appears. The text is primarily in Bengali. Do not add any conversational filler, explanations, or markdown blocks. Just return the raw extracted text."
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the text from this document page:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            temperature=0.1, 
            max_tokens=4096
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""

async def process_pdf_bytes(pdf_bytes):
    extracted_text = ""
    try:
        pages_to_process = await asyncio.to_thread(
            convert_from_bytes, 
            pdf_bytes,
            first_page=1,
            last_page=MAX_PAGES_PER_PDF
        )
        
        for i, page_image in enumerate(pages_to_process):
            base64_img = image_to_base64(page_image)
            page_text = await perform_ocr(base64_img)
            
            if page_text:
                extracted_text += f"\n--- Page {i+1} ---\n{page_text}\n"
            
            page_image.close()
            await asyncio.sleep(4.0) # Thermal safety cooldown
                
    except Exception as e:
        print(f"\n[!] PDF Conversion Error: {e}")
        
    return extracted_text

# ==========================================
# 4. WORKER POOL ARCHITECTURE (PRODUCER-CONSUMER)
# ==========================================
async def network_scout_worker(network_queue, gpu_queue, http_client):
    """50 constant workers checking pages for PDF links."""
    while True:
        url = await network_queue.get()
        try:
            pdf_links = []
            
            # 🛡️ FIX 1: Ruthless timeout for every phase
            timeout = httpx.Timeout(8.0, connect=4.0, read=4.0, pool=4.0)
            
            # 🛡️ FIX 2: Mimic a browser and force the server to release the socket
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Connection": "close"
            }
            
            response = await http_client.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            
            # 🛡️ FIX 3: ONLY parse actual HTML! 
            content_type = response.headers.get('Content-Type', '').lower()
            
            if response.status_code == 200 and 'text/html' in content_type:
                # 🛡️ FIX 4: Safety limit on size (2MB)
                if len(response.text) < 2_000_000: 
                    soup = BeautifulSoup(response.text, 'html.parser')
                    for a_tag in soup.find_all('a', href=True):
                        if a_tag['href'].lower().endswith('.pdf'):
                            pdf_links.append(urljoin(url, a_tag['href']))
            
            pdf_links = list(set(pdf_links))
            if pdf_links:
                await gpu_queue.put((url, pdf_links))
            else:
                log_checkpoint(url)
                pbar.update(1)
                
        except Exception:
            # Silently swallow timeouts and move on
            log_checkpoint(url)
            pbar.update(1)
        finally:
            network_queue.task_done()

async def gpu_processing_worker(gpu_queue, http_client):
    """2 isolated workers protecting VRAM/RAM doing the heavy downloading and OCR."""
    while True:
        url, pdf_links = await gpu_queue.get()
        combined_pdf_text = ""
        
        for pdf_url in pdf_links:
            try:
                pdf_response = await http_client.get(pdf_url, timeout=25.0, follow_redirects=True)
                
                if pdf_response.status_code == 200:
                    pdf_bytes = pdf_response.content
                    
                    # 2. THE ABSOLUTE SHIELD: Magic bytes check
                    if not pdf_bytes.lstrip().startswith(b'%PDF'):
                        del pdf_response
                        del pdf_bytes
                        continue 
                        
                    # 3. Size Shield: Reject over 50MB
                    if len(pdf_bytes) > 50_000_000:
                        del pdf_response
                        del pdf_bytes
                        continue
                        
                    del pdf_response 
                    
                    # 4. Process OCR
                    ocr_text = await process_pdf_bytes(pdf_bytes)
                    del pdf_bytes
                    
                    if ocr_text.strip():
                        combined_pdf_text += f"\n\nDocument Source: {pdf_url}\n{ocr_text}"
            except Exception:
                continue
                
        if combined_pdf_text.strip():
            await append_to_markdown(url, combined_pdf_text)
            
        log_checkpoint(url)
        pbar.update(1)
        gpu_queue.task_done()
        gc.collect()
        
def log_checkpoint(url):
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{url}\n")

# ==========================================
# 5. ORCHESTRATOR
# ==========================================
async def run_vision_fleet():
    global pbar
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    
    print("🚀 Initializing Decoupled Queue-Driven Vision Fleet (TARGETED TOPICS)...")
    processed_urls = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            processed_urls = set(line.strip() for line in f)

    # Fetch ONLY targeted URLs
    all_targeted_urls = fetch_all_crawled_urls()
    pending_urls = [url for url in all_targeted_urls if url not in processed_urls]
    
    print(f"📊 Target DB URLs: {len(all_targeted_urls)} | Already Checked: {len(processed_urls)} | Pending: {len(pending_urls)}")
    
    if not pending_urls:
        print("✅ All targeted URLs have been checked. Fleet shutting down.")
        return

    # Create queues
    network_queue = asyncio.Queue()
    gpu_queue = asyncio.Queue()

    # Load pending target URLs into the network queue
    for url in pending_urls:
        network_queue.put_nowait(url)

    print(f"⚡ Launching fleet: {NUM_NETWORK_WORKERS} Dedicated Scouts, {NUM_GPU_WORKERS} VRAM Isolation Workers...")
    
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    
    pbar = tqdm(total=len(pending_urls), desc="Fleet Processing (Targeted)")

    async with httpx.AsyncClient(verify=False, limits=limits, follow_redirects=True) as http_client:
        scout_tasks = [
            asyncio.create_task(network_scout_worker(network_queue, gpu_queue, http_client))
            for _ in range(NUM_NETWORK_WORKERS)
        ]
        
        gpu_tasks = [
            asyncio.create_task(gpu_processing_worker(gpu_queue, http_client))
            for _ in range(NUM_GPU_WORKERS)
        ]

        await network_queue.join()
        await gpu_queue.join()

        for task in scout_tasks + gpu_tasks:
            task.cancel()

    pbar.close()
    print("\n🎉 Targeted Vision OCR Fleet Run Complete! The queue-based fleet finished smoothly.")

if __name__ == "__main__":
    asyncio.run(run_vision_fleet())