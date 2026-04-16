import asyncio
import asyncpg

# ---------------- CONFIGURATION ---------------- #
DB_USER = "postgres"         
DB_PASS = "password"         
DB_NAME = "gov_bd_db"        
DB_HOST = "127.0.0.1"
DB_PORT = 5432 
OUTPUT_FILE = "output.txt"
# ----------------------------------------------- #

async def fetch_top_5():
    print(f"[*] Connecting to PostgreSQL and saving output to {OUTPUT_FILE}...")
    
    conn = await asyncpg.connect(
        user=DB_USER, 
        password=DB_PASS, 
        database=DB_NAME, 
        host=DB_HOST, 
        port=DB_PORT
    )
    
    query = "select count(*) from gov_bd_pages where status='success';"
    records = await conn.fetch(query)
    
    # Open the file for writing ('w' overwrites, 'a' appends)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"[*] Successfully fetched {len(records)} rows.\n\n")
        
        for i, record in enumerate(records, 1):
            f.write(f"=== Row {i} ===\n")
            for key, value in record.items():
                str_val = str(value)
                
                # Write to file instead of printing to console
                f.write(f"{key.upper()}: {str_val}\n")
            f.write("-" * 40 + "\n")
            
    await conn.close()
    print("[*] Done!")

if __name__ == "__main__":
    asyncio.run(fetch_top_5())