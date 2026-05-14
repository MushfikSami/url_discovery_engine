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
    
    # STEP 1: The Initial Call
    # Notice we REMOVED the stop tokens here. Because we are using native `tools`, 
    # we want the model to cleanly output the tool JSON, not try to format text.
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
    # This loop ONLY runs if the model natively decides to use a tool
    # --- THE REACT LOOP ---
    while getattr(msg, 'tool_calls', None) and loop_count < max_loops:
        
        # --- THE FIX: DEDUPLICATE PARALLEL TOOL CALLS ---
        unique_tool_calls = {}
        for tool_call in msg.tool_calls:
            # Create a unique signature for the tool call
            call_signature = f"{tool_call.function.name}_{tool_call.function.arguments}"
            if call_signature not in unique_tool_calls:
                unique_tool_calls[call_signature] = tool_call
        
        # Now only iterate through the unique, filtered calls
        for call_signature, tool_call in unique_tool_calls.items():
            tool_name = tool_call.function.name
            tool_args = tool_call.function.arguments
            
            yield f"🔍 *অ্যাকশন (Action):* `{tool_name}` কল করা হচ্ছে...\n*প্যারামিটার:* `{tool_args}`\n"
            
            # Execute the tool
            observation = execute_tool(tool_name, tool_args)
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id, # Must use the original ID so the LLM doesn't crash
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
            top_logprobs=1,
            stop=["<|im_end|>"]
        )
        
        msg = response.choices[0].message
        messages.append(msg)
        loop_count += 1

    # --- FINAL CONFIDENCE CHECK ---
    content = msg.content or ""
    
    # Safely extract logprobs
    token_logprobs = response.choices[0].logprobs.content if getattr(response.choices[0], 'logprobs', None) else []
    
    total_prob = 0.0
    valid_tokens = 0
    
    for token_data in token_logprobs:
        prob = math.exp(token_data.logprob) 
        total_prob += prob
        valid_tokens += 1
        
    avg_confidence = total_prob / valid_tokens if valid_tokens > 0 else 1.0 # Default to 1.0 if no logprobs (e.g. cached response)
    
    print(f"📊 [Diagnostic] Generation Confidence: {avg_confidence * 100:.2f}%")
    
    # The Anti-Hallucination Kill Switch
    if avg_confidence < threshold_pct:
        print(f"🚨 [WARNING] Confidence ({avg_confidence * 100:.2f}%) below threshold! Halting.")
        yield "\nদুঃখিত, এই তথ্যের ব্যাপারে আমি সম্পূর্ণ নিশ্চিত নই। অনুগ্রহ করে সরকারি ওয়েবসাইট চেক করুন।"
    else:
        # Clean up the output if the model prepended "Final Answer:" 
        clean_content = content.replace("**Final Answer:**", "").replace("Final Answer:", "").strip()
        yield f"\n{clean_content}"