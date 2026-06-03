import psycopg2
import textwrap

# Database configuration - match this to your DB_CONFIG
DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

def verify_crawler_results():
    print("🔍 Auditing Crawler Fleet Results...\n")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # 1. Check Top-Level Domain Status
        print("📊 1. SEED DOMAIN STATUS (From seed_websites)")
        print("-" * 40)
        cursor.execute("SELECT status, COUNT(*) FROM seed_websites GROUP BY status;")
        for status, count in cursor.fetchall():
            print(f"   - {status.upper()}: {count} domains")
        print("   (If 'PENDING' is 0, the fleet finished the new batch!)")

        # 2. Check Individual Page Queue
        print("\n🕷️ 2. PAGE QUEUE STATUS (From spider_queue)")
        print("-" * 40)
        cursor.execute("SELECT status, COUNT(*) FROM spider_queue GROUP BY status;")
        for status, count in cursor.fetchall():
            print(f"   - {status.upper()}: {count} pages")

        # 3. Check Final Extracted Data
        print("\n💾 3. EXTRACTED DATA (From crawled_data)")
        print("-" * 40)
        cursor.execute("SELECT COUNT(*) FROM crawled_data;")
        total_data = cursor.fetchone()[0]
        print(f"   - Total Markdown documents saved in DB: {total_data}")

        # 4. Preview the Data to ensure parsers didn't fail
        print("\n👀 4. PAYLOAD SANITY CHECK (Random Sample of 3)")
        print("-" * 40)
        # Using ORDER BY RANDOM() to grab a random sample of crawled data
        cursor.execute("""
            SELECT url, LENGTH(raw_markdown), snippet 
            FROM crawled_data 
            WHERE LENGTH(raw_markdown) > 0
            ORDER BY RANDOM() 
            LIMIT 3;
        """)
        
        for url, length, snippet in cursor.fetchall():
            print(f"🌐 URL: {url}")
            print(f"📏 Size: {length} characters of Markdown")
            # Wrap the snippet text so it formats nicely in the terminal
            short_snippet = textwrap.shorten(snippet or "No snippet", width=80, placeholder="...")
            print(f"📝 Snippet: {short_snippet}\n")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Database error: {e}")

if __name__ == "__main__":
    verify_crawler_results()