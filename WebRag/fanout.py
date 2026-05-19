# fanout.py
from config import client, VLLM_MODEL

def generate_wikipedia_query(user_prompt: str) -> str:
    """Uses vLLM to extract the optimal Wikipedia search entity."""
    
    system_prompt = """
    You are an expert search query generator. 
    Your task is to take a user's question and convert it into a single, highly accurate search phrase optimized for a Wikipedia search engine.
    
    RULES:
    1. Output ONLY the exact search phrase. No explanations, no quotes, no markdown.
    2. If the user asks in Bengali, output the exact Bengali Wikipedia title.
    3. Remove conversational filler (e.g., 'who is', 'tell me about', 'what is the history of').
    """

    try:
        response = client.chat.completions.create(
            model=VLLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0, # Zero temperature for deterministic extraction
            max_tokens=20
        )
        
        search_query = response.choices[0].message.content.strip()
        print(f"🧠 [Fanout] Converted '{user_prompt}' -> '{search_query}'")
        return search_query

    except Exception as e:
        print(f"❌ [Fanout Error] vLLM failed: {e}")
        return user_prompt # Fallback to raw prompt if LLM fails