from openai import OpenAI
from tools import BD_GOV_TOOLS, execute_tool
from config import client, MASTER_SYSTEM_PROMPT
import math

def generate_response(user_message: str, history: list, model_name="qwen36", threshold_pct: float = 0.85):
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT}]
    
    # Robust history parser for newer Gradio versions
    for item in history:
        if isinstance(item, dict) and "role" in item:
            messages.append({"role": item["role"], "content": item["content"]})
        elif hasattr(item, "role") and hasattr(item, "content"):
            messages.append({"role": item.role, "content": item.content})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
            
    messages.append({"role": "user", "content": user_message})

    yield "🧠 *চিন্তা প্রক্রিয়া শুরু হচ্ছে (Analyzing query...)*\n"
    
    # --- BUG FIX 2: Added logprobs to the FIRST call ---
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        tools=BD_GOV_TOOLS,
        tool_choice="auto",
        temperature=0.0,
        logprobs=True,
        top_logprobs=1
    )
    
    msg = response.choices[0].message
    messages.append(msg) 

    loop_count = 0
    max_loops = 3 
    
    # --- THE REACT LOOP ---
    while msg.tool_calls and loop_count < max_loops:
        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            tool_args = tool_call.function.arguments
            
            yield f"🔍 *অ্যাকশন (Action):* `{tool_name}` কল করা হচ্ছে...\n*প্যারামিটার:* `{tool_args}`\n"
            
            # Execute the tool
            observation = execute_tool(tool_name, tool_args)
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": str(observation)
            })
            
        yield "⚙️ *পর্যবেক্ষণ (Observation) প্রাপ্ত। ডাটাবেস থেকে তথ্য প্রসেস করা হচ্ছে...*\n"
        
        # Generate next thought/response
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=BD_GOV_TOOLS,
            tool_choice="auto", 
            temperature=0.0, 
            logprobs=True,   
            top_logprobs=1   
        )
        
        # --- BUG FIX 1: Update msg and increment loop_count ---
        msg = response.choices[0].message
        messages.append(msg)
        loop_count += 1

    # --- FINAL CONFIDENCE CHECK ---
    content = msg.content or ""
    
    # Safely extract logprobs (vLLM sometimes returns None if the output is empty)
    token_logprobs = response.choices[0].logprobs.content if response.choices[0].logprobs else []
    
    total_prob = 0.0
    valid_tokens = 0
    
    for token_data in token_logprobs:
        prob = math.exp(token_data.logprob) 
        total_prob += prob
        valid_tokens += 1
        
    avg_confidence = total_prob / valid_tokens if valid_tokens > 0 else 0.0
    
    print(f"📊 [Diagnostic] Generation Confidence: {avg_confidence * 100:.2f}%")
    
    # The Anti-Hallucination Kill Switch
    if avg_confidence < threshold_pct:
        print(f"🚨 [WARNING] Confidence ({avg_confidence * 100:.2f}%) below threshold! Halting.")
        # --- BUG FIX 3: Yield instead of Return ---
        yield "\nদুঃখিত, এই তথ্যের ব্যাপারে আমি সম্পূর্ণ নিশ্চিত নই। অনুগ্রহ করে সরকারি ওয়েবসাইট চেক করুন।"
    else:
        yield f"\n{content}"