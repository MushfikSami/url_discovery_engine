import asyncio
import asyncpg
import json

# ---------------- CONFIGURATION ---------------- #
DB_USER = "postgres"         
DB_PASS = "password"         
DB_NAME = "bd_gov_db"        
DB_HOST = "127.0.0.1"
DB_PORT = 5432 
# ----------------------------------------------- #

async def export_db_for_pageindex():
    print("[*] Connecting to PostgreSQL...")
    pool = await asyncpg.create_pool(user=DB_USER, password=DB_PASS, database=DB_NAME, host=DB_HOST, port=DB_PORT)
    
    # NEW: Fetching summary and keywords along with the raw markdown
    # (I left LIMIT 100 here for a quick test, remove it when you are ready for the full run)
    query = """
        SELECT url, summary, keywords, raw_markdown 
        FROM websites 
        WHERE status = 'success' AND raw_markdown IS NOT NULL 

    """
    
    async with pool.acquire() as conn:
        records = await conn.fetch(query)
        
    print(f"[*] Exporting {len(records)} websites with AI intelligence to Markdown...")
    
    with open("../data/bd_gov_ecosystem.md", "w", encoding="utf-8") as f:
        # The single # represents the Root Node
        f.write("# Bangladesh Government Web Ecosystem\n\n")
        
        for record in records:
            url = record['url']
            summary = record['summary']
            
            # Format the JSON keywords array into a clean comma-separated string
            try:
                keywords_list = json.loads(record['keywords'])
                keywords_str = ", ".join(keywords_list)
            except:
                keywords_str = record['keywords']
                
            # Push original markdown headers down a level to protect the tree structure
            content = record['raw_markdown'].replace('\n# ', '\n### ') 
            
            # THE MAGIC HAPPENS HERE: Injecting the AI intelligence directly into the node
            f.write(f"## {url}\n\n")
            f.write(f"**সারসংক্ষেপ (Summary):** {summary}\n\n")
            f.write(f"**কিওয়ার্ড (Keywords):** {keywords_str}\n\n")
            f.write(f"**বিস্তারিত তথ্য (Detailed Content):**\n")
            f.write(f"{content}\n\n")
            f.write("---\n\n") # Visual separator
            
    await pool.close()
    print("[+] Export complete: bd_gov_ecosystem.md now contains AI summaries and keywords!")

if __name__ == "__main__":
    asyncio.run(export_db_for_pageindex())