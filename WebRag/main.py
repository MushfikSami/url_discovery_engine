# main.py
from fanout import generate_wikipedia_query
from search import search_wikipedia
from parser import extract_markdown_from_url

def execute_webrag_pipeline(user_input: str):
    print("\n" + "="*50)
    print(f"🚀 Starting Pipeline for: '{user_input}'")
    print("="*50)

    # Step 1: LLM Fanout (Intent to Keyword)
    optimized_query = generate_wikipedia_query(user_input)
    
    # Step 2: SearXNG (Keyword to URL)
    target_url = search_wikipedia(optimized_query)
    
    if not target_url:
        return "Pipeline aborted: No URL found."

    # Step 3: Docling (URL to Markdown)
    final_markdown = extract_markdown_from_url(target_url)
    
    return final_markdown

# --- Test the Pipeline ---
if __name__ == "__main__":
    # Test with a Bengali temporal query
    user_question = "Who is the current Prime Minister of Bangladesh?"
    
    context_markdown = execute_webrag_pipeline(user_question)
    with open("final_context.md", "w", encoding="utf-8") as f:
        f.write(context_markdown)
    print("\n" + "="*50)
    print("📊 FINAL CONTEXT EXTRACTED (Preview):")
    print("="*50)
    print(context_markdown[:1000])