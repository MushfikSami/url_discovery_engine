import psycopg2

# Adjust if your credentials differ
DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

def total_ecosystem_reset():
    print("🧹 Starting Total Database Purge for National Portal Seed Re-Architecture...")
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Disable triggers temporarily to ensure fast execution and avoid lock stalls
        cursor.execute("SET CONSTRAINTS ALL DEFERRED;")

        # 1. Purge Crawled Data Payloads
        print("Executing TRUNCATE on crawled_data...")
        cursor.execute("TRUNCATE TABLE crawled_data RESTART IDENTITY CASCADE;")
        print("   ✅ Wiped all extracted page data payloads.")

        # 2. Purge Domain Hierarchy Mappings
        print("Executing TRUNCATE on domain_hierarchy...")
        cursor.execute("TRUNCATE TABLE domain_hierarchy RESTART IDENTITY CASCADE;")
        print("   ✅ Cleared old domain relationship mappings.")

        # 3. Purge Spider Processing Queue
        print("Executing TRUNCATE on spider_queue...")
        cursor.execute("TRUNCATE TABLE spider_queue RESTART IDENTITY CASCADE;")
        print("   ✅ Purged all pending and in-flight crawl targets.")

        # 4. Clear and Reset Seed Websites
        # Since the foundational seeds are changing to a strict District-level maximum,
        # we completely clear this out so your new bangladesh.gov.bd scrapper has a clean slate.
        print("Executing TRUNCATE on seed_websites...")
        cursor.execute("TRUNCATE TABLE seed_websites RESTART IDENTITY CASCADE;")
        print("   ✅ Flushed old seed domain cache.")

        # Commit the transaction to apply changes permanently
        conn.commit()
        print("\n🎉 Total Reset Complete! The database tables are empty, clean, and perfectly primed for the new District-level seeds.")
        
    except Exception as e:
        print(f"\n❌ Database error during absolute purge: {e}")
        if conn:
            print("🔄 Rolling back changes...")
            conn.rollback()
    finally:
        if conn:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    # Safety confirmation prompt to prevent accidental execution in production envs
    confirm = input("⚠️ WARNING: This will completely wipe all crawled data, queues, and seed lists. Type 'RESET' to confirm: ")
    if confirm.strip() == "RESET":
        total_ecosystem_reset()
    else:
        print("❌ Reset aborted by user.")