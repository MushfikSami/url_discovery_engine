# app.py

import re
import asyncio
import gradio as gr
from openai import AsyncOpenAI

# Custom Module Imports
from config import MASTER_SYSTEM_PROMPT, MODEL_NAME, VLLM_URL
from es_engine import get_query_embedding, retrieve_context # Exposing for external evaluation scripts

vllm_client = AsyncOpenAI(api_key="no-key", base_url=VLLM_URL)

async def chat_interface(user_message, history):
    """The Asynchronous Autonomous Multi-Hop Agent orchestrator."""
    
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

    current_display = "🧠 **Autonomous Agent initialized. Analyzing query...**\n\n"
    yield current_display
    
    collected_sources = set()

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
                temperature=0.1, 
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

            # Final Answer Check
            if re.search(r"(?i)\**final answer:?\**|\**উত্তর:\**", agent_output):
                if collected_sources:
                    source_block = "\n\n**Sources:**\n" + "\n".join(list(collected_sources))
                    current_display += source_block
                yield current_display
                is_resolved = True
                continue

            # Tool Interceptor
            action_match = re.search(r"Action:\s*(\w+)\([\'\"]?(.*?)[\'\"]?\)", agent_output)
            if action_match:
                tool_name = action_match.group(1)
                search_query = action_match.group(2)
                full_action_string = action_match.group(0).lower()
                
                current_display += f"🔍 *Executing {tool_name} for: \"{search_query}\"*...\n"
                yield current_display
                
                if full_action_string in executed_actions:
                    obs_text = "System Warning: You just executed this exact search. Do not repeat failed searches. Use completely different keywords or output 'Final Answer:' stating the data is unavailable."
                else:
                    executed_actions.add(full_action_string)

                    if tool_name in ["hybrid_search", "vector_search", "search", "exact_keyword_search","lexical_search"]:
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
                messages.append({"role": "user", "content": f"Observation: {obs_text}\n\nIf you have the answer, output 'Final Answer:'. If not, expand your query and use another Action."})
            else:
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": "System Error: You must format your response with exactly 'Action: tool_name(\"query\")' or 'Final Answer:'."})

        except Exception as e:
            yield current_display + f"\n❌ **Agent Loop Error:** {str(e)}"
            is_resolved = True


# ==========================================
# 5. LAUNCH UI
# ==========================================

demo = gr.ChatInterface(
    fn=chat_interface,
    title="Bangladesh Govt Services AI (Autonomous Agent)",
    description="Ask complex questions. The AI will reason step-by-step, utilize search tools, prevent repetitive loops, and combine multiple sources to give a formal Bengali response.",
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)