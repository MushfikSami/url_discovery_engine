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
MAX_HOPS = 5 # The agent can try up to 5 times to find the answer
# ----------------------------------------------- #

# ==========================================
# 1. MASTER SYSTEM PROMPT
# ==========================================

MASTER_SYSTEM_PROMPT = """
You are the Official Digital AI Assistant for the Government of Bangladesh. Your absolute priority is to provide accurate, official information to citizens by reasoning through complex queries and using your available search tools to retrieve verified data from the official government tree-index.

--- STRICT GUARDRAILS (CRITICAL) ---
You must evaluate every user query against the following safety protocols BEFORE taking any action or generating any thought.
You MUST IMMEDIATELY REJECT any query that involves, asks for, or implies:
1. Self-sabotage, self-harm, or suicide.
2. Sabotage, destruction, or vandalism of state, private, or public property.
3. Terrorism, violence, or illegal activities.
4. Unethical manipulation, bypassing, or hacking of government systems, portals, or laws.
If a query violates ANY of these rules, you must abort all tool usage and output EXACTLY and ONLY this phrase:
"দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"

--- LINGUISTIC RULES ---
1. OUTPUT LANGUAGE: You must communicate EXCLUSIVELY in highly formal, official Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা).
2. NO COLLOQUIALISMS: Do not use regional dialects, slang, or informal phrasing.
3. TONE: Maintain a respectful, bureaucratic, highly objective, and empathetic tone.

--- TOOL REPOSITORY ---
You have access to the following tool to find information from the local tree database:
- `search_tree(query: str)`: Searches the hierarchical government database. If your first search fails, use this tool again with BROADER or alternative Bengali keywords (Query Expansion).

--- REASONING FRAMEWORK & CHAIN OF THOUGHT ---
You are a Multi-Hop Reasoning Agent. You investigate questions step-by-step using the ReAct (Reason + Act) methodology. 

If you NEED to search for information, you MUST output:
Thought: [Analyze the query. Formulate the best search terms in Bengali.]
Action: [The exact tool name and query, e.g., search_tree("your search terms")]
Observation: [WAIT for the system to provide results. Do not write this yourself.]

CRITICAL ESCAPE HATCH: If you have searched 2 or 3 times using different variations of the keywords and the information is clearly missing, DO NOT keep searching endlessly. Accept that the data is unavailable.

If you ALREADY HAVE the necessary information, OR if you realize the data is missing after trying to search, DO NOT output an Action. You must IMMEDIATELY output:
Final Answer: [Your strictly formal Bengali response based ONLY on the observations. If data is missing, politely explain that it is not in the system's database.]

--- EXAMPLES ---

Example 1: Successful multi-hop retrieval
User: [A complex question asking for two distinct pieces of information, e.g., Concept A and Concept B]
Thought: The user is asking about [Concept A] and [Concept B]. I need to find information on both. First, I will search for [Concept A].
Action: search_tree("[Search query for Concept A]")
Observation: [System returns relevant text about Concept A...]
Thought: I have found the information for [Concept A]. Now I need to find information for [Concept B].
Action: search_tree("[Search query for Concept B]")
Observation: [System returns relevant text about Concept B...]
Thought: I have successfully retrieved all necessary data. I will now format the final answer in formal Bengali.
Final Answer: [A highly formal, official Bengali response synthesizing the findings about Concept A and Concept B based strictly on the observations.]

Example 2: Triggering the Escape Hatch when data is missing
User: [A question about a specific, possibly non-existent policy or service]
Thought: I need to search the database for rules regarding [Specific Policy/Service].
Action: search_tree("[Highly specific search query]")
Observation: No relevant documents found in the local tree index.
Thought: The first search yielded no results. I will broaden my search terms to see if the information falls under a wider category.
Action: search_tree("[Broader alternative search query]")
Observation: No relevant documents found in the local tree index.
Thought: I have searched multiple times using different keyword variations, but the observation shows no relevant documents exist in the database. I will use the escape hatch and inform the user.
Final Answer: দুঃখিত, আমার বর্তমান ডাটাবেসে এই নির্দিষ্ট বিষয়ের কোনো সরকারি নীতিমালা বা তথ্য সংরক্ষিত নেই।
"""

# ==========================================
# 2. Utilities & Index Initialization
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
# 3. Tool Logic: Search & Dynamic Chunking
# ==========================================
def execute_tree_search(query):
    """The tool called by the LLM. Uses BM25 to find top nodes and dynamically chunks the text."""
    if not bm25 or not toc:
        return "Database not loaded properly."

    tokenized_query = tokenize(query)
    
    # 1. Broad Node Retrieval (Top 5)
    top_nodes = bm25.get_top_n(tokenized_query, toc, n=5)
    if not top_nodes:
        return "No relevant documents found in the local tree index."

    selected_ids = [n['node_id'] for n in top_nodes]
    
    # 2. Extract Full Text
    raw_full_texts = []
    for node in all_nodes:
        if str(node.get('node_id', '')) in selected_ids:
            raw_full_texts.append(f"Source: {node.get('title', 'Unknown')}\n{node.get('text', '')}")
            
    combined_raw_text = "\n\n".join(raw_full_texts)
    
    # 3. Dynamic Chunking (Prevents context overflow)
    text_chunks = chunk_text(combined_raw_text, chunk_size=2000, overlap=300)
    
    if len(text_chunks) > 3:
        chunk_corpus = [tokenize(chunk) for chunk in text_chunks]
        chunk_bm25 = BM25Okapi(chunk_corpus)
        best_chunks = chunk_bm25.get_top_n(tokenized_query, text_chunks, n=3)
        final_context = "\n\n...[text omitted]...\n\n".join(best_chunks)
    else:
        final_context = combined_raw_text

    return final_context

# ==========================================
# 4. Master QA Bot (ReAct Agent Loop)
# ==========================================
async def process_query(message, history):
    
    if not bm25 or not toc:
        yield "❌ **Error:** Database not loaded properly."
        return

    # 1. Initialize System Prompt
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT}]
    
    # 2. Add Sanitized Chat History
    for item in history[-6:]: 
        role = ""
        content = ""
        if isinstance(item, dict):
            role = item.get("role", "user")
            content = str(item.get("content", ""))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            user_text = str(item[0] or "")
            ai_text = str(item[1] or "")
            if "**উত্তর:**" in ai_text: ai_text = ai_text.split("**উত্তর:**")[-1].strip()
            elif "Final Answer:" in ai_text: ai_text = ai_text.split("Final Answer:")[-1].strip()
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": ai_text})
            continue

        if role == "assistant":
            if "**উত্তর:**" in content: content = content.split("**উত্তর:**")[-1].strip()
            elif "Final Answer:" in content: content = content.split("Final Answer:")[-1].strip()
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    current_display = "🧠 **Autonomous Tree Agent initialized...**\n\n"
    yield current_display
    
    # --- AUTONOMOUS STATE VARIABLES ---
    is_resolved = False
    executed_actions = set() # Memory to prevent infinite repetitive loops
    safety_breaker = 0 # Ultimate server safeguard (not a hop limit)

    # --- THE AUTONOMOUS LOOP ---
    while not is_resolved:
        safety_breaker += 1
        if safety_breaker > 15:
            yield current_display + "\n⚠️ **System Failsafe Triggered: Agent exceeded safe computation limits.**"
            break

        try:
            stream = await vllm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                max_tokens=4096,
                temperature=0.2, 
                stream=True,
                stop=["Observation:"]
            )
            
            agent_output = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    text_chunk = chunk.choices[0].delta.content
                    agent_output += text_chunk
                    yield current_display + agent_output
            
            current_display += agent_output + "\n\n"
            
            # Guardrail Check
            if "দুঃখিত, সরকারি নীতিমালার আওতায়" in agent_output:
                yield current_display + "\n🛑 **GUARDRAIL TRIGGERED**"
                is_resolved = True
                continue

            # Resolution Check (Success or Graceful Failure)
            if re.search(r"(?i)\**Final Answer:\**|\**উত্তর:\**", agent_output):
                is_resolved = True
                yield current_display
                continue

            # Action Interceptor
            action_match = re.search(r"Action:\s*(\w+)\([\'\"]?(.*?)[\'\"]?\)", agent_output)
            if action_match:
                tool_name = action_match.group(1)
                search_query = action_match.group(2)
                full_action_string = action_match.group(0).lower()
                
                current_display += f"🌳 *Searching Tree for: \"{search_query}\"*...\n"
                yield current_display
                
                # --- REPETITION DETECTION (The alternative to max_hops) ---
                if full_action_string in executed_actions:
                    obs_text = "System Warning: You just executed this exact search. Do not repeat failed searches. Use completely different keywords or output 'Final Answer:' stating the data is unavailable."
                else:
                    executed_actions.add(full_action_string)
                    
                    if tool_name in ["search_tree", "search", "hybrid_search"]:
                        obs_text = await asyncio.to_thread(execute_tree_search, search_query)
                    else:
                        obs_text = f"Error: Tool '{tool_name}' not recognized. Please use 'search_tree'."
                    
                current_display += f"📄 *Tree nodes retrieved. Feeding back to AI...*\n\n"
                yield current_display
                
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": f"Observation: {obs_text}\n\nIf you have the answer, output 'Final Answer:'. If not, expand your query and use another Action."})
            
            else:
                # Formatting Failsafe
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": "System Error: You must format your response with exactly 'Action: tool_name(\"query\")' or 'Final Answer:'."})

        except Exception as e:
            yield current_display + f"\n❌ **Agent Loop Error:** {str(e)}"
            is_resolved = True
# ==========================================
# 5. Launch App
# ==========================================
demo = gr.ChatInterface(
    fn=process_query,
    title="🌳 BD Gov Discovery Engine (ReAct Agent)",
    description="Ask questions about Bangladesh Government services. The AI navigates a hierarchical Tree Index and uses ReAct prompting to dynamically expand its searches.",
    examples=["খতিয়ান (ই-পর্চা) তোলার নিয়ম কি?", "প্রাথমিক শিক্ষা অধিদপ্তরের বদলি নীতিমালা কি?", "বাঘাইছড়ি উপজেলার পর্যটন কেন্দ্রগুলো কী কী?"],
    fill_height=True
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)