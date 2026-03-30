import asyncio
import asyncpg

# ---------------- CONFIGURATION ---------------- #
DB_USER = "postgres"         
DB_PASS = "password"         
DB_NAME = "bd_gov_db"        
DB_HOST = "127.0.0.1"
DB_PORT = 5432 
# ----------------------------------------------- #

async def fetch_top_5():
    print("[*] Connecting to PostgreSQL...")
    conn = await asyncpg.connect(
        user=DB_USER, 
        password=DB_PASS, 
        database=DB_NAME, 
        host=DB_HOST, 
        port=DB_PORT
    )
    
    # The SQL query: Select all columns (*), limit to 5 rows
    query = "SELECT * FROM websites LIMIT 5;"
    
    records = await conn.fetch(query)
    
    print(f"[*] Successfully fetched {len(records)} rows.\n")
    
    for i, record in enumerate(records, 1):
        print(f"=== Row {i} ===")
        # Loop through every column and print its value
        for key, value in record.items():
            str_val = str(value)
            # Truncate massive text blocks so your terminal remains readable
            if len(str_val) > 150:
                str_val = str_val[:150] + "... [TRUNCATED]"
            print(f"{key.upper()}: {str_val}")
        print("-" * 40)
            
    await conn.close()

if __name__ == "__main__":
    asyncio.run(fetch_top_5())