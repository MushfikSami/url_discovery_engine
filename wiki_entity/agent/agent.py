from openai import OpenAI
from tools import BD_GOV_TOOLS, execute_tool
from config import client, MASTER_SYSTEM_PROMPT
# Initialize local vLLM

def generate_response(user_message: str, history: list):
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT}]
    
    for human, assistant in history:
        messages.append({"role": "user", "content": human})
        messages.append({"role": "assistant", "content": assistant})
        
    messages.append({"role": "user", "content": user_message})

    yield "🧠 *চিন্তা প্রক্রিয়া শুরু হচ্ছে (Analyzing query...)*"
    
    response = client.chat.completions.create(
        model="qwen36", 
        messages=messages,
        tools=BD_GOV_TOOLS,
        tool_choice="auto"
    )
    
    msg = response.choices[0].message
    messages.append(msg) 

    loop_count = 0
    max_loops = 3 
    
    while msg.tool_calls and loop_count < max_loops:
        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            tool_args = tool_call.function.arguments
            
            yield f"🔍 *অ্যাকশন (Action):* `{tool_name}` কল করা হচ্ছে...\n*প্যারামিটার:* `{tool_args}`"
            
            # This now hits your local 3-millisecond QLever database!
            observation = execute_tool(tool_name, tool_args)
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": observation
            })
            
        yield "⚙️ *পর্যবেক্ষণ (Observation) প্রাপ্ত। ডাটাবেস থেকে তথ্য প্রসেস করা হচ্ছে...*"
        
        response = client.chat.completions.create(
            model="qwen36",
            messages=messages,
            tools=BD_GOV_TOOLS,
            tool_choice="auto"
        )
        msg = response.choices[0].message
        messages.append(msg)
        loop_count += 1

    yield msg.content