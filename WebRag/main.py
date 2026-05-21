# main.py
from fanout import generate_wikipedia_query
from search import search_mediawiki
from parser import extract_markdown_from_wiki

def execute_webrag_pipeline(user_input: str):
    print("\n" + "="*50)
    print(f"🚀 Starting Pipeline for: '{user_input}'")
    print("="*50)

    # Step 1: LLM Fanout
    optimized_query = generate_wikipedia_query(user_input)
    
    # Step 2: MediaWiki OpenSearch (Now includes suggestions!)
    target_url, suggestions = search_mediawiki(optimized_query)
    
    if not target_url:
        return f"Pipeline aborted: No URL found. (Suggestions: {suggestions})"

    # Step 3: Secure Fetch & Docling Parse
    final_markdown = extract_markdown_from_wiki(target_url)
    
    return final_markdown

if __name__ == "__main__":
    # Example usage
    user_query = "শহীদ মিনার কে নকশা করেছেন?"
    result = execute_webrag_pipeline(user_query)
    print("\n" + "="*50)
    print("📄 Final Markdown Output:")
    print("="*50)
    print(result[:2500])  # Print the first 500 characters for brevity