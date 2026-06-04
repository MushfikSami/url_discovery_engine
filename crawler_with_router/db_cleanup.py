import psycopg2

# Adjust if your credentials differ
DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

def cleanup_recent_batch():
    print("🧹 Starting Database Cleanup for the 2026-06-03 batch...")
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # The date of the botched crawl from your logs
        TARGET_DATE = '2026-06-03'

        # 1. Delete any corrupted/empty payloads saved during this batch
        cursor.execute("""
            DELETE FROM crawled_data 
            WHERE url IN (
                SELECT url FROM spider_queue WHERE added_at >= %s
            );
        """, (TARGET_DATE,))
        deleted_data = cursor.rowcount
        print(f"✅ Deleted {deleted_data} payloads from crawled_data.")

        # 2. Reset the affected seed websites back to 'pending'
        cursor.execute("""
            UPDATE seed_websites 
            SET status = 'pending' 
            WHERE website_url IN (
                SELECT DISTINCT base_domain FROM spider_queue WHERE added_at >= %s
            );
        """, (TARGET_DATE,))
        reset_seeds = cursor.rowcount
        print(f"✅ Reset {reset_seeds} seed domains to 'pending'.")

        # 3. Clean out the domain hierarchy map for these seeds
        cursor.execute("""
            DELETE FROM domain_hierarchy 
            WHERE website IN (
                SELECT DISTINCT base_domain FROM spider_queue WHERE added_at >= %s
            );
        """, (TARGET_DATE,))
        deleted_hierarchy = cursor.rowcount
        print(f"✅ Cleared {deleted_hierarchy} domain hierarchy maps.")

        # 4. Completely purge the spider_queue for this batch 
        # (This forces the crawler to re-discover the links naturally)
        cursor.execute("""
            DELETE FROM spider_queue WHERE added_at >= %s;
        """, (TARGET_DATE,))
        deleted_queue = cursor.rowcount
        print(f"✅ Purged {deleted_queue} queued pages.")

        # Commit the transaction
        conn.commit()
        print("\n🎉 Cleanup Complete! The DB is primed for a fresh run.")
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    cleanup_recent_batch()