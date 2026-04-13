# app.py
import asyncio
import re
import gradio as gr
from openai import AsyncOpenAI

# Custom Module Imports
# --- Replace your current local imports with this ---
try:
    from agent.config import MASTER_SYSTEM_PROMPT, MODEL_NAME
    from agent.utils import tokenize, chunk_text 
    from agent.tree_index import execute_tree_search, bm25, toc, all_nodes 
except ModuleNotFoundError:
    from config import MASTER_SYSTEM_PROMPT, MODEL_NAME
    from utils import tokenize, chunk_text 
    from tree_index import execute_tree_search, bm25, toc, all_nodes 
# ----------------------------------------------------
vllm_client = AsyncOpenAI(base_url="http://localhost:5000/v1", api_key="no-key")

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
    executed_actions = set() 
    safety_breaker = 0 

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
            if "দুঃখিত, সরকারি নীতিমালার আওতায়" in agent_output:
                yield current_display + "\n🛑 **GUARDRAIL TRIGGERED**"
                is_resolved = True
                continue

            # Resolution Check
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