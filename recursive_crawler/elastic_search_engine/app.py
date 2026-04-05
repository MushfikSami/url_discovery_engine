import os
import re
import numpy as np
import gradio as gr
from elasticsearch import Elasticsearch
import tritonclient.http as httpclient
from transformers import AutoTokenizer
from openai import AsyncOpenAI
import asyncio

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
vllm_client = AsyncOpenAI(
    api_key="no-key",
    base_url="http://localhost:5000/v1"
)

# ==========================================
# 2. MASTER PROMPT
# ==========================================

MASTER_SYSTEM_PROMPT = """
You are the Official Digital AI Assistant for the Government of Bangladesh. Your absolute priority is to provide accurate, official information to citizens by reasoning through complex queries and using your available search tools to retrieve verified data from the .gov.bd ecosystem.

--- STRICT GUARDRAILS (CRITICAL) ---
You must evaluate every user query against the following safety protocols BEFORE taking any action or generating any thought.
You MUST IMMEDIATELY REJECT any query that involves, asks for, or implies:
1. Self-sabotage, self-harm, or suicide.
2. Sabotage, destruction, or vandalism of state, private, or public property.
3. Terrorism, violence, or illegal activities.
4. Unethical manipulation, bypassing, or hacking of government systems, portals, or laws.
If a query violates ANY of these rules, you must abort all tool usage and output EXACTLY and ONLY this phrase:
"দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"

--- LINGUISTIC RULES ---
1. OUTPUT LANGUAGE: You must communicate EXCLUSIVELY in highly formal, official Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা).
2. NO COLLOQUIALISMS: Do not use regional dialects, slang, or informal phrasing (e.g., use 'সনদপত্র' instead of 'সার্টিফিকেট', 'উত্তোলন' instead of 'তোলার নিয়ম').
3. TONE: Maintain a respectful, bureaucratic, highly objective, and empathetic tone. Do not use emojis. Do not use exclamation points unless absolutely necessary.

--- TOOL REPOSITORY ---
You have access to the following tools to find information. You must evaluate the user's query to decide which tool (if any) is best suited for the task.
- `hybrid_search(query: str)`: Uses both semantic meaning and exact keyword matching. Best for general questions, procedures, or specific government rules.
- `vector_search(query: str)`: Uses semantic meaning.
- `lexical_search(query: str)`: Uses exact keyword matching.

--- REASONING FRAMEWORK & CHAIN OF THOUGHT ---
You are a Multi-Hop Reasoning Agent. You investigate questions step-by-step using the ReAct (Reason + Act) methodology. 

If you NEED to search for information, you MUST output:
Thought: [Think about what you need to search for in formal Bengali]
Action: [The exact tool name and query, e.g., hybrid_search("ই-পাসপোর্ট ফি")]
Observation: [WAIT for the system to provide results. Do not write this yourself.]

CRITICAL ESCAPE HATCH: If you have searched 1 or 2 times and the specific information is clearly missing from the observations, DO NOT keep searching endlessly. You must accept that the data is unavailable.

If you ALREADY HAVE the necessary information, OR if you realize the data is missing after trying to search, DO NOT output an Action. You must IMMEDIATELY output:
Final Answer: [Your strictly formal Bengali response based ONLY on the observations. If data is missing, politely explain that the specific rules are not currently available in the system's database.]

--- EXAMPLES ---

Example 1: Successful multi-hop retrieval
User: আমি ঢাকা থেকে বদলি হয়ে সিলেটে গেলে আমার বাড়ি ভাড়া ভাতা কত হবে?
Thought: User is asking about the change in House Rent Allowance. I need the allowance rates for both Dhaka and Sylhet.
Action: hybrid_search("ঢাকা সিটি কর্পোরেশন বাড়ি ভাড়া ভাতা")
Observation: [System returns: "ঢাকা মেট্রোপলিটন এলাকার জন্য ৬০%..."]
Thought: I have the Dhaka allowance. Now I need Sylhet.
Action: hybrid_search("সিলেট সিটি কর্পোরেশন বাড়ি ভাড়া ভাতা")
Observation: [System returns: "সিলেট সিটি কর্পোরেশনের জন্য ৪৫%..."]
Thought: I have all the necessary data. I will now provide the answer.
Final Answer: সরকারি বিধিমালা অনুযায়ী, ঢাকা মেট্রোপলিটন এলাকায় আপনার বাড়ি ভাড়া ভাতা মূল বেতনের ৬০%। সিলেটে বদলি হলে তা ৪৫% হবে।

Example 2: Triggering the Escape Hatch when data is missing
User: বাংলাদেশ সরকারের নিয়ম অনুযায়ী চাঁদে জমি কেনার পদ্ধতি কী?
Thought: I need to search the database for rules regarding buying land on the moon.
Action: hybrid_search("চাঁদে জমি কেনার সরকারি নিয়ম")
Observation: No relevant government documents found for this exact query.
Thought: I have searched for this information, but the observation shows no relevant documents exist in the database. I will use the escape hatch and inform the user.
Final Answer: দুঃখিত, আমার বর্তমান ডাটাবেসে চাঁদে জমি ক্রয় সংক্রান্ত কোনো সরকারি নীতিমালা বা তথ্য সংরক্ষিত নেই।
"""
# ==========================================
# 3. CORE RAG FUNCTIONS
# ==========================================

def get_query_embedding(text):
    """Tokenizes a single query and fetches its vector from Triton."""
    formatted_text = f"task: search result | query: {text}"
    encoded = tokenizer([formatted_text], padding=True, truncation=True, max_length=512, return_tensors="np")
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
    search_query = {
        "knn": {
            "field": "chunk_vector",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": 50,
            "boost": 0.5 
        },
        "query": {
            "match": {
                "chunk_text": {
                    "query": query_text,
                    "boost": 1.5 
                }
            }
        },
        "size": top_k,
        "_source": ["chunk_text", "url", "site_title"]
    }
    try:
        response = es.search(index=INDEX_NAME, body=search_query)
        hits = response["hits"]["hits"]
        contexts, sources = [], []
        for hit in hits:
            source_data = hit["_source"]
            contexts.append(source_data.get("chunk_text", ""))
            title = source_data.get("site_title", "").strip()
            if not title or len(title) < 3 or "```" in title:
                title = "Official BD Government Document"
            url = source_data.get("url", "#")
            if url != "#":
                sources.append(f"- [{title}]({url})")
        return "\n\n".join(contexts), list(set(sources))
    except Exception as e:
        print(f"[!] Elasticsearch Error: {e}")
        return "", []

# ==========================================
# 4. AGENTIC CHATBOT LOGIC
# ==========================================

MAX_HOPS = 5

async def chat_interface(user_message, history):
    """The Asynchronous Multi-Hop Agent orchestrator."""
    
    # 1. Initialize System Prompt
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT}]
    
    # 2. Add brief, SANITIZED chat history
    for item in history[-6:]: 
        role = ""
        content = ""
        
        if isinstance(item, dict):
            role = item.get("role", "user")
            content = str(item.get("content", ""))
            
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            user_text = str(item[0] or "")
            ai_text = str(item[1] or "")
            
            if "**উত্তর:**" in ai_text:
                ai_text = ai_text.split("**উত্তর:**")[-1].strip()
            elif "Final Answer:" in ai_text:
                ai_text = ai_text.split("Final Answer:")[-1].strip()
                
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": ai_text})
            continue

        if role == "assistant":
            if "**উত্তর:**" in content:
                content = content.split("**উত্তর:**")[-1].strip()
            elif "Final Answer:" in content:
                content = content.split("Final Answer:")[-1].strip()
                
        if content:
            messages.append({"role": role, "content": content})

    # 3. Add the current user message
    messages.append({"role": "user", "content": user_message})

    current_display = "🧠 **Agent initialized. Analyzing query...**\n\n"
    yield current_display
    
    collected_sources = set()

    for hop in range(MAX_HOPS):
        try:
            # ---> CRITICAL: AWAIT THE ASYNC STREAM <---
            stream = await vllm_client.chat.completions.create(
                model="qwen35",
                messages=messages,
                max_tokens=4096,
                temperature=0.1, 
                stream=True,
                stop=["Observation:"]
            )
            
            agent_output = ""
            # ---> CRITICAL: ASYNC FOR LOOP <---
            async for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    text_chunk = chunk.choices[0].delta.content
                    agent_output += text_chunk
                    yield current_display + agent_output
            
            current_display += agent_output + "\n\n"
            
            # Guardrail Check
            if "দুঃখিত, সরকারি নীতিমালার আওতায়" in agent_output:
                yield current_display + "\n🛑 **GUARDRAIL TRIGGERED**"
                return

            # Final Answer Check
            if re.search(r"(?i)\**final answer:?\**|\**উত্তর:\**", agent_output):
                if collected_sources:
                    source_block = "\n\n**Sources:**\n" + "\n".join(list(collected_sources))
                    current_display += source_block
                yield current_display
                return

            # Tool Interceptor
            action_match = re.search(r"Action:\s*(\w+)\([\'\"]?(.*?)[\'\"]?\)", agent_output)
            if action_match:
                tool_name = action_match.group(1)
                search_query = action_match.group(2)
                
                current_display += f"🔍 *Executing {tool_name} for: \"{search_query}\"*...\n"
                yield current_display
                
                if tool_name in ["hybrid_search", "vector_search", "search", "exact_keyword_search","lexical_search"]:
                    # ---> CRITICAL: QUARANTINE SYNCHRONOUS CALLS TO SEPARATE THREADS <---
                    query_vector = await asyncio.to_thread(get_query_embedding, search_query)
                    obs_text, new_sources = await asyncio.to_thread(retrieve_context, search_query, query_vector)
                    
                    collected_sources.update(new_sources)
                    if not obs_text.strip():
                        obs_text = "No relevant government documents found for this exact query. Try a different search term."
                
                elif tool_name == "no_tool_needed":
                    obs_text = "No search required. Proceed to answer."
                else:
                    obs_text = f"Error: Tool '{tool_name}' not recognized."
                    
                current_display += f"📄 *Observation retrieved. Feeding back to AI...*\n\n"
                yield current_display
                
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": f"Observation: {obs_text}\n\nIf you have the answer, output 'Final Answer:'. If not, use another Action."})
            else:
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": "System Error: You must format your response with exactly 'Action: tool_name(\"query\")' or 'Final Answer:'."})

        except Exception as e:
            yield current_display + f"\n❌ **Agent Loop Error:** {str(e)}"
            return

    yield current_display + f"\n⚠️ **Agent timed out after maximum research hops ({MAX_HOPS}/{MAX_HOPS}).**"# ==========================================
# 5. LAUNCH UI
# ==========================================

demo = gr.ChatInterface(
    fn=chat_interface,
    title="Bangladesh Govt Services AI (Agentic)",
    description="Ask complex questions. The AI will reason step-by-step, utilize search tools, and combine multiple sources to give a formal Bengali response.",
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)