import json
import asyncio
import re
import gradio as gr
from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi

# ---------------- CONFIGURATION ---------------- #
vllm_client = AsyncOpenAI(base_url="http://localhost:5000/v1", api_key="no-key")
MODEL_NAME = "qwen35"
TREE_PATH = "../PageIndex/results/bd_gov_ecosystem_structure.json" 
MAX_RETRIES = 2 # The agent will try up to 2 different search strategies
# ----------------------------------------------- #

# ==========================================
# 1. Utilities & Initialization
# ==========================================
def flatten_tree(nodes_list):
    flat_list = []
    for node in nodes_list:
        flat_list.append(node)
        if 'nodes' in node and isinstance(node['nodes'], list):
            flat_list.extend(flatten_tree(node['nodes']))
    return flat_list

def tokenize(text):
    if not text: return []
    return re.findall(r'\w+', str(text).lower())

def chunk_text(text, chunk_size=2000, overlap=300):
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

try:
    print("[*] Loading and Flattening Official PageIndex Tree...")
    with open(TREE_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
        
    if isinstance(raw_data, dict):
        root_nodes = raw_data.get('structure', raw_data.get('nodes', []))
    else:
        root_nodes = raw_data

    all_nodes = flatten_tree(root_nodes)

    toc = []
    for n in all_nodes:
        text = n.get('text', '')
        summary = ""
        if "**সারসংক্ষেপ (Summary):**" in text:
            summary = text.split("**সারসংক্ষেপ (Summary):**")[1].split("**কিওয়ার্ড")[0].strip()
            
        toc.append({
            "node_id": n.get('node_id', ''), 
            "title": n.get('title', n.get('heading', 'Unknown')), 
            "summary": summary[:250] 
        })

    toc = [n for n in toc if n["summary"]]
    print(f"[+] Successfully flattened {len(all_nodes)} total nodes.")
    
    print("[*] Building BM25 Search Index for all nodes (CPU Only)...")
    corpus = [tokenize(n['title'] + " " + n['summary']) for n in toc]
    bm25 = BM25Okapi(corpus)
    print("[+] BM25 Lexical Index Ready! VRAM preserved.")

except Exception as e:
    print(f"[!] Warning: Could not load tree structure. Error: {e}")
    all_nodes = []
    toc = []
    bm25 = None

# ==========================================
# 2. Master QA Bot (Self-Reflection RAG)
# ==========================================
async def process_query(message, history):
    
    if not bm25 or not toc:
        yield "❌ **Error:** Database not loaded properly."
        return

    previous_failed_queries = []

    # --- THE AGENTIC LOOP ---
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            yield f"🔄 **Self-Reflection Triggered (Attempt {attempt}/{MAX_RETRIES})!**\n*Attempt {attempt-1} failed to find the exact answer. Broadening search parameters...*"
        else:
            yield "🧠 **Stage -1: Query Expansion...**\n*Translating your intent into official search terms...*"
        
        # Adaptive Prompt: Changes based on whether it's the first try or a retry
        if attempt == 1:
            expansion_prompt = f"""
            SYSTEM: You are an expert search query generator for the Bangladesh Government web ecosystem.
            User's original query: "{message}"
            
            CRITICAL INSTRUCTIONS:
            1. Understand the core intent of the user's messy or informal query.
            2. Rewrite the query into 3 distinct, highly professional Bengali search phrases.
            3. Include official government terms and correct spelling.
            4. Respond STRICTLY in JSON format as a list of strings.
            """
        else:
            expansion_prompt = f"""
            SYSTEM: You are an expert search query generator for the Bangladesh Government web ecosystem.
            User's original query: "{message}"
            
            PREVIOUS FAILED SEARCHES: {previous_failed_queries}
            
            CRITICAL INSTRUCTIONS:
            1. The previous search terms FAILED to find the answer.
            2. You must BROADEN the scope. Think of higher-level ministries, alternative synonyms, or broader categories.
            3. Generate 3 COMPLETELY DIFFERENT professional Bengali search phrases.
            4. Respond STRICTLY in JSON format as a list of strings.
            """
        
        try:
            exp_response = await vllm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": expansion_prompt}],
                temperature=0.4, # Slightly higher temp for better brainstorming on retries
                response_format={"type": "json_object"}
            )
            
            raw_exp = json.loads(exp_response.choices[0].message.content)
            
            expanded_queries = []
            if isinstance(raw_exp, dict):
                values = list(raw_exp.values())
                if len(values) > 0: expanded_queries = values[0]
            elif isinstance(raw_exp, list):
                expanded_queries = raw_exp
                
            if not isinstance(expanded_queries, list): expanded_queries = [str(expanded_queries)]
        except Exception as e:
            expanded_queries = []
            
        expanded_queries.append(message)
        expanded_queries = list(set(expanded_queries))
        
        # Save these in case we need to retry again
        previous_failed_queries.extend(expanded_queries)
        
        yield f"🧠 **Stage -1 Complete (Attempt {attempt})!**\n*Searching for variations: {expanded_queries}*\n\n⚡ **Stage 0: BM25 Pre-Filtering...**"

        # --- STAGE 0: MULTI-BM25 PRE-FILTERING ---
        top_indices_set = set()
        for query_variant in expanded_queries:
            tokenized_query = tokenize(query_variant)
            indices = bm25.get_top_n(tokenized_query, range(len(toc)), n=10)
            top_indices_set.update(indices)
        
        combined_top_indices = list(top_indices_set)[:25]
        
        filtered_toc = [toc[i] for i in combined_top_indices]
        filtered_toc_json = json.dumps(filtered_toc, ensure_ascii=False, indent=2)

        # --- PHASE 1: LOCAL REASONING ---
        yield f"⚡ **Stage 0 Complete!** BM25 isolated top matches.\n\n🔍 **Phase 1: AI Reasoning...**\n*Evaluating documents...*"

        reasoning_prompt = f"""
            SYSTEM: You are an intelligent routing agent navigating a hierarchical Table of Contents for Bangladesh Government Services.
            
            CRITICAL INSTRUCTIONS:
            1. Read the User Query in Bengali and understand its core intent.
            2. Identify the 'node_id's of the sections most logically related to the query.
            3. BE FLEXIBLE: Look for conceptual matches.
            
            Filtered Tree Index:
            {filtered_toc_json}
            
            User Query: "{message}"
            
            Respond STRICTLY in JSON format as a list of strings containing the best 1 to 3 node_ids.
            """
        
        try:
            response = await vllm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": reasoning_prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            
            raw_result = json.loads(response.choices[0].message.content)
            
            selected_ids = []
            if isinstance(raw_result, dict):
                values = list(raw_result.values())
                if len(values) > 0: selected_ids = values[0]
            elif isinstance(raw_result, list):
                selected_ids = raw_result
                
            if not isinstance(selected_ids, list): selected_ids = [str(selected_ids)] if selected_ids else []
            
            # If Reasoning fails to find a node, loop to next attempt
            if not selected_ids:
                 if attempt < MAX_RETRIES:
                     continue # Jump back to the top of the loop and broaden search
                 else:
                     yield "❌ **Final Attempt Complete!**\n*No relevant local nodes found after multiple strategies.*\n\n**Response:**\nআমি দুঃখিত, আমার কাছে এই তথ্য নেই। (I am sorry, I do not have this information in my local database.)"
                     return

            # --- STAGE 1.5: DYNAMIC CONTEXT WINDOWING ---
            yield f"🔍 **Phase 1 Complete!**\n*Routed to nodes: {selected_ids}*\n\n✂️ **Stage 1.5: Dynamic Chunking...**"        
            
            raw_full_texts = []
            for node in all_nodes:
                if str(node.get('node_id', '')) in selected_ids:
                    raw_full_texts.append(f"Source: {node.get('title', 'Unknown')}\n{node.get('text', '')}")
                    
            combined_raw_text = "\n\n".join(raw_full_texts)
            text_chunks = chunk_text(combined_raw_text, chunk_size=2000, overlap=300)
            
            if len(text_chunks) > 3:
                chunk_corpus = [tokenize(chunk) for chunk in text_chunks]
                chunk_bm25 = BM25Okapi(chunk_corpus)
                tokenized_orig_query = tokenize(message)
                best_chunks = chunk_bm25.get_top_n(tokenized_orig_query, text_chunks, n=3)
                final_context = "\n\n...[text omitted]...\n\n".join(best_chunks)
            else:
                final_context = combined_raw_text

            yield "✂️ **Stage 1.5 Complete!**\n\n⚙️ **Phase 2: Generating Bengali response...**"
            
            # --- PHASE 2: LOCAL GENERATION ---
            answer_prompt = f"""
            SYSTEM: You are a highly accurate official assistant for the Government of Bangladesh.
            
            CRITICAL INSTRUCTIONS:
            1. Read the Context provided below carefully.
            2. If the context contains the answer OR highly relevant partial information, synthesize it STRICTLY in Bengali (বাংলা).
            3. If the Context is completely blank or 100% irrelevant to the question, output exactly: "[NOT_FOUND]" and nothing else.
            4. Do NOT provide general advice without local context, do NOT hallucinate links.
            
            Context:
            {final_context}
            
            User Query: {message}
            Response:
            """
            
            final_answer = await vllm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": answer_prompt}],
                temperature=0.1
            )
            
            result_text = final_answer.choices[0].message.content.strip()
            
            # Check if generation phase realized the context was bad
            if "[NOT_FOUND]" in result_text:
                if attempt < MAX_RETRIES:
                    continue # Try again!
                else:
                    yield "❌ **Final Attempt Complete!**\n*Found related documents, but they didn't contain the specific answer.*\n\n**Response:**\nআমি দুঃখিত, আমার কাছে এই নির্দিষ্ট তথ্যটি নেই।"
                    return
            
            yield f"**[Local Database Answer]**\n*Selected Nodes:* `{selected_ids}` (Found on Attempt {attempt})\n\n---\n\n{result_text}"
            return # Success! Break out of the loop.
            
        except Exception as e:
            yield f"❌ **Error occurred on Attempt {attempt}:**\n{str(e)}"
            if attempt == MAX_RETRIES: return

# ==========================================
# 3. Launch App
# ==========================================
demo = gr.ChatInterface(
    fn=process_query,
    title="🇧🇩 BD Gov Discovery Engine (Agentic Retry)",
    description="Ask questions about Bangladesh Government services. Features **Self-Reflection**. If it fails to find an answer initially, it will dynamically rewrite its own search strategy and try again.",
    examples=["খতিয়ান (ই-পর্চা) তোলার নিয়ম কি?", "প্রাথমিক শিক্ষা অধিদপ্তরের বদলি নীতিমালা কি?", "বাঘাইছড়ি উপজেলার পর্যটন কেন্দ্রগুলো কী কী?"],
    fill_height=True
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)