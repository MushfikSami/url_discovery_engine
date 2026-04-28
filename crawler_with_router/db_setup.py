# db_setup.py
import psycopg2

DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

def init_db():
    print("[*] Initializing Domain-by-Domain Spider Database Schema...")
    
    # 1. Create DB if it doesn't exist
    conn_default = psycopg2.connect(**{**DB_CONFIG, "dbname": "postgres"})
    conn_default.autocommit = True
    cursor_default = conn_default.cursor()
    try:
        cursor_default.execute("CREATE DATABASE gov_spider_db;")
    except psycopg2.errors.DuplicateDatabase:
        pass
    finally:
        cursor_default.close()
        conn_default.close()

    # 2. Create Tables
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # Tracks the progress of your text file of domains
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seed_websites (
            website_url TEXT PRIMARY KEY,
            status VARCHAR(20) DEFAULT 'pending' -- 'pending', 'processing', 'completed'
        );
    """)

    # Tracks the individual webpages for a specific domain
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spider_queue (
            url TEXT PRIMARY KEY,
            base_domain TEXT,
            status VARCHAR(20) DEFAULT 'pending', 
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Final outputs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS domain_hierarchy (
            website TEXT PRIMARY KEY,
            web_pages TEXT[] DEFAULT '{}'
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawled_data (
            url TEXT PRIMARY KEY,
            raw_markdown TEXT,
            snippet TEXT,
            keywords TEXT[]
        );
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("[+] Database tables initialized successfully.")

if __name__ == "__main__":
    init_db()