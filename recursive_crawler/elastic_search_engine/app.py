import os
import numpy as np
import gradio as gr
from elasticsearch import Elasticsearch
import tritonclient.http as httpclient
from transformers import AutoTokenizer
from openai import OpenAI

# ==========================================
# 1. SERVER CONNECTIONS
# ==========================================

# Triton (EmbeddingGemma)
TRITON_URL = "localhost:7000"
try:
    triton_client = httpclient.InferenceServerClient(url=TRITON_URL)
    print(f"[+] Connected to Triton Server at {TRITON_URL}")
except Exception as e:
    print(f"[!] Triton Connection Error: {e}")

print("[*] Loading Gemma Tokenizer...")
tokenizer = AutoTokenizer.from_pretrained("google/embeddinggemma-300m")

# Elasticsearch
es = Elasticsearch("http://localhost:9200")
INDEX_NAME = "bd_gov_chunks"

# vLLM (Qwen API)
# vLLM perfectly emulates the OpenAI API, so we just use the official OpenAI client!
vllm_client = OpenAI(
    api_key="no-key",
    base_url="http://localhost:5000/v1"
)

# ==========================================
# 2. CORE RAG FUNCTIONS
# ==========================================

def get_query_embedding(text):
    """Tokenizes a single query and fetches its vector from Triton."""
    # EmbeddingGemma requires this specific prefix for questions
    formatted_text = f"task: search result | query: {text}"
    
    encoded = tokenizer(
        [formatted_text], 
        padding=True, 
        truncation=True, 
        max_length=512, # Safe token clamp
        return_tensors="np"
    )
    
    input_ids = encoded["input_ids"].astype(np.int64)
    attention_mask = encoded["attention_mask"].astype(np.int64)
    
    inputs = [
        httpclient.InferInput("input_ids", input_ids.shape, "INT64"),
        httpclient.InferInput("attention_mask", attention_mask.shape, "INT64")
    ]
    inputs[0].set_data_from_numpy(input_ids)
    inputs[1].set_data_from_numpy(attention_mask)
    
    outputs = [httpclient.InferRequestedOutput("sentence_embedding")]
    
    response = triton_client.infer(model_name="gemma_embedding", inputs=inputs, outputs=outputs)
    return response.as_numpy("sentence_embedding")[0].tolist()

def retrieve_context(query_text, query_vector, top_k=5):
    """Searches Elasticsearch using HYBRID search (BM25 + k-NN)."""
    
    # --- HYBRID SEARCH PAYLOAD ---
    search_query = {
        # 1. The Vector Search (Good for context)
        "knn": {
            "field": "chunk_vector",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": 50,
            "boost": 0.5 # We give vectors a slightly lower weight to reduce boilerplate
        },
        # 2. The Lexical BM25 Search (Good for exact keywords)
        "query": {
            "match": {
                "chunk_text": {
                    "query": query_text,
                    "boost": 1.5 # We boost exact keyword matches heavily!
                }
            }
        },
        "size": top_k, # Ensure it only returns the combined top 5
        "_source": ["chunk_text", "url", "site_title"]
    }
    
    try:
        response = es.search(index=INDEX_NAME, body=search_query)
        hits = response["hits"]["hits"]
        
        contexts = []
        sources = []
        for hit in hits:
            source_data = hit["_source"]
            contexts.append(source_data.get("chunk_text", ""))
            
            # --- METADATA SANITIZER ---
            title = source_data.get("site_title", "").strip()
            if not title or len(title) < 3 or "```" in title:
                title = "Official BD Government Document"
                
            url = source_data.get("url", "#")
            if url != "#":
                sources.append(f"- [{title}]({url})")
            
        final_context = "\n\n".join(contexts)
        
        # --- TERMINAL DEBUG LOGGER ---
        print("\n" + "="*40)
        print(f"[DEBUG] HYBRID RETRIEVAL SCORES:")
        for idx, hit in enumerate(hits):
            print(f"Rank {idx+1}: Score = {hit['_score']} | Source = {hit['_source'].get('site_title', 'Unknown')}")
        print("="*40 + "\n")
        
        return final_context, list(set(sources))
        
    except Exception as e:
        print(f"[!] Elasticsearch Error: {e}")
        return "", []# ==========================================
# 3. GRADIO CHATBOT LOGIC
# ==========================================

def chat_interface(user_message, history):
    """The main brain that routes data between Triton, ES, and vLLM."""
    
    # Step 1: Embed the query
    query_vector = get_query_embedding(user_message)
    
    # Step 2: Retrieve context
    context_text, sources = retrieve_context(user_message, query_vector)
    
    if not context_text:
        yield "I'm sorry, I couldn't connect to the government database to retrieve information."
        return

    # Step 3: Build the System Prompt for Qwen
    system_prompt = f"""You are a helpful AI assistant dedicated to answering questions about Bangladesh government services.
You will be provided with context retrieved directly from official .gov.bd websites. 
Answer the user's question accurately using ONLY the provided context. If the context does not contain the answer, politely state that you cannot find the specific information in the government database. Do not invent information. Respond in the same language the user asks the question in (Bengali or English).

--- OFFICIAL CONTEXT ---
{context_text}
------------------------
"""

    # Step 4: Stream the response from vLLM
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add brief chat history so it remembers the conversation
    for item in history[-6:]: # Keep recent memory
        if isinstance(item, dict):
            # Handles newest Gradio dict format
            messages.append({"role": item.get("role", "user"), "content": str(item.get("content", ""))})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            # Handles classic Gradio list format (ignoring extra metadata)
            messages.append({"role": "user", "content": str(item[0] or "")})
            messages.append({"role": "assistant", "content": str(item[1] or "")})
            
    messages.append({"role": "user", "content": user_message})

    try:
        stream = vllm_client.chat.completions.create(
            model="qwen35", # This name can be arbitrary when hitting your local vLLM
            messages=messages,
            max_tokens=1024,
            temperature=0.3, # Keep it low for factual retrieval
            stream=True
        )
        
        partial_response = ""
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                partial_response += chunk.choices[0].delta.content
                yield partial_response
                
        # Step 5: Append Source Links at the end
        if sources:
            source_block = "\n\n**Sources:**\n" + "\n".join(sources)
            partial_response += source_block
            yield partial_response

    except Exception as e:
        yield f"An error occurred while communicating with the LLM: {str(e)}"

# ==========================================
# 4. LAUNCH UI
# ==========================================

demo = gr.ChatInterface(
    fn=chat_interface,
    title="Bangladesh Govt Services AI",
    description="Ask questions about official BD government services. The AI retrieves real-time context from indexed .gov.bd websites.",
    
)

if __name__ == "__main__":
    # Launch on 0.0.0.0 so you can access it via your server's IP address
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)