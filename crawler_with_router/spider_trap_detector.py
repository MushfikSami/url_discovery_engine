import psycopg2
from db_setup import DB_CONFIG

def detect_spider_traps():
    print("🔍 Analyzing Database for Spider Traps and Duplicates...\n")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # ==========================================
        # 1. FIND THE BIGGEST OFFENDERS
        # ==========================================
        print("🚨 TOP 10 MOST BLOATED DOMAINS:")
        print("--------------------------------------------------")
        cursor.execute("""
            SELECT base_domain, COUNT(*) as page_count 
            FROM spider_queue 
            GROUP BY base_domain 
            ORDER BY page_count DESC 
            LIMIT 10;
        """)
        for row in cursor.fetchall():
            print(f"[{row[1]} pages] - {row[0]}")

        # ==========================================
        # 2. DETECT QUERY PARAMETER TRAPS
        # ==========================================
        print("\n🪤 QUERY PARAMETER SUSPECTS (URLs containing '?'):")
        print("--------------------------------------------------")
        cursor.execute("""
            SELECT COUNT(*) FROM spider_queue WHERE url LIKE '%?%';
        """)
        param_count = cursor.fetchone()[0]
        print(f"Total URLs with query parameters: {param_count}")
        
        if param_count > 0:
            cursor.execute("""
                SELECT url FROM spider_queue WHERE url LIKE '%?%' LIMIT 5;
            """)
            print("Examples:")
            for row in cursor.fetchall():
                print(f"  -> {row[0]}")

        # ==========================================
        # 3. DETECT CONTENT DUPLICATION
        # ==========================================
        # How many times does the exact same Markdown text appear across multiple URLs?
        print("\n👯 CONTENT DUPLICATION (Different URLs, Exact Same Page):")
        print("--------------------------------------------------")
        cursor.execute("""
            SELECT COUNT(*) 
            FROM (
                SELECT raw_markdown 
                FROM crawled_data 
                WHERE length(raw_markdown) > 100
                GROUP BY raw_markdown 
                HAVING COUNT(*) > 1
            ) as duplicate_content;
        """)
        duplicate_content_count = cursor.fetchone()[0]
        print(f"Total unique pages that have been crawled multiple times under different URLs: {duplicate_content_count}")

    except Exception as e:
        print(f"[!] Database Error: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    detect_spider_traps()