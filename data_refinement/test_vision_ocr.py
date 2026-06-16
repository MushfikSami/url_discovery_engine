import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pdf2image import convert_from_bytes
import base64
import io
from openai import AsyncOpenAI

# ==========================================
# CONFIGURATION
# ==========================================
VLLM_API_BASE = "http://localhost:5000/v1" 
VLLM_API_KEY = "no_key"  
MODEL_NAME = "qwen36"  # Ensure this matches your running vLLM model

client = AsyncOpenAI(api_key=VLLM_API_KEY, base_url=VLLM_API_BASE)

def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

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
    except Exception as e:
        print(f"\n[!] LLM OCR Error: {e}")
        return ""

async def test_pdf_ocr(url):
    print("="*60)
    print(f"🔍 [VISION TESTER] Hunting for PDFs on: {url}")
    print("="*60)
    
    pdf_links = []
    async with httpx.AsyncClient(verify=False, timeout=15.0) as http_client:
        response = await http_client.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            if a_tag['href'].lower().endswith('.pdf'):
                pdf_links.append(urljoin(url, a_tag['href']))

    if not pdf_links:
        print("⚠️ No PDFs found.")
        return
        
    target_pdf = pdf_links[0]
    print(f"📄 Found PDF! Downloading: {target_pdf}")
    
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
        response = await http_client.get(target_pdf)
        pdf_bytes = response.content
        
    print("⚙️ Converting PDF to Images...")
    pages = convert_from_bytes(pdf_bytes)
    
    print(f"👁️ Sending Page 1 (out of {len(pages)}) to Local vLLM for OCR...")
    base64_img = image_to_base64(pages[0])
    
    extracted_text = await perform_ocr(base64_img)
    
    print("\n✅ [SUCCESS] Extracted OCR Text:")
    print("-" * 60)
    print(extracted_text)
    print("-" * 60)

if __name__ == "__main__":
    target = input("🌐 Enter a URL to test Vision OCR: ").strip()
    if not target.startswith('http'):
        target = 'https://' + target
    asyncio.run(test_pdf_ocr(target))