# llm_extractor.py
import requests
import json
from config import VLLM_API_BASE

def get_vllm_model():
    try:
        response = requests.get(f"{VLLM_API_BASE}/models")
        return response.json()['data'][0]['id']
    except Exception as e:
        raise ConnectionError(f"🚨 Cannot connect to vLLM at {VLLM_API_BASE}. Error: {e}")

MODEL_NAME = get_vllm_model()

def extract_structured_entities(text):
    """
    Passes text to vLLM and forces it to return categorized graph entities in JSON format.
    """
    system_prompt = (
        "You are an expert Bengali Knowledge Graph extractor. "
        "Read the provided text and extract the core entities into specific categories. "
        "You MUST respond ONLY with a valid JSON object. Do not include any markdown formatting or explanations. "
        "The JSON must have exactly these three keys: "
        "'locations' (list of strings, e.g., division, district, upazila), "
        "'organizations' (list of strings, e.g., ministries, departments, schools), "
        "'services' (list of strings, e.g., policies, allowances, certificates)."
    )

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text[:2000]}
        ],
        "temperature": 0.0,
        "max_tokens": 150
    }

    try:
        response = requests.post(f"{VLLM_API_BASE}/chat/completions", json=payload)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content'].strip()
        
        # Clean up in case the LLM wrapped it in markdown code blocks
        if content.startswith("```json"):
            content = content[7:-3].strip()
            
        return json.loads(content)
        
    except Exception as e:
        print(f"⚠️ vLLM Extraction failed or returned invalid JSON. Error: {e}")
        # Return empty graph structure on failure
        return {"locations": [], "organizations": [], "services": []}