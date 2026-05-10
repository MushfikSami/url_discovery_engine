import gradio as gr
from agent import generate_response

# Custom CSS for a government-style official look
custom_css = """
.gradio-container { font-family: 'Kalpurush', Arial, sans-serif; }
#title { text-align: center; color: #006a4e; font-weight: bold; }
"""

with gr.Blocks() as demo:
    gr.Markdown("# 🇧🇩 বাংলাদেশ সরকারি সেবা এআই (BD Govt Service AI)", elem_id="title")
    gr.Markdown("### সরকারি তথ্য ও সেবার প্রাতিষ্ঠানিক ডিজিটাল অ্যাসিস্ট্যান্ট", elem_id="title")
    
    # The core Chat Interface
    chat_interface = gr.ChatInterface(
        fn=generate_response,
        chatbot=gr.Chatbot(height=600, show_label=False),
        textbox=gr.Textbox(placeholder="আপনার প্রশ্ন লিখুন (যেমন: ই-পাসপোর্ট ফি কত?)...", container=False, scale=7),
        
        examples=[
            "ঢাকা সম্পর্কে বলুন?",
            "ঢাকা ইউনিভার্সিটি কবে প্রতিষ্ঠিত হয়েছিল?",
            "বাংলাদেশের রাজধানী কী?"
        ],
        title=None
    )

if __name__ == "__main__":
    print("🚀 Launching BD Government AI Agent Prototype...")
    demo.launch(server_name="0.0.0.0", server_port=7861, share=True)