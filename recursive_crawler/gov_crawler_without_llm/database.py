# database.py

import psycopg2
try:
    from config import DB_CONFIG
except ModuleNotFoundError:
    from .config import DB_CONFIG

def get_connection():
    """Returns a fresh database connection."""
    return psycopg2.connect(**DB_CONFIG)

def setup_database():
    """Creates the gov_bd_pages table if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gov_bd_pages (
            url TEXT PRIMARY KEY,
            title TEXT,
            markdown_body TEXT,
            status VARCHAR(50) DEFAULT 'pending',
            crawled_at TIMESTAMP
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()
    print("[+] Database table 'gov_bd_pages' verified/ready.")

def insert_pending_url(url):
    """Inserts a new URL as pending, ignoring if it already exists."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO gov_bd_pages (url, status) 
        VALUES (%s, 'pending') 
        ON CONFLICT (url) DO NOTHING;
    """, (url,))
    conn.commit()
    cursor.close()
    conn.close()

def update_url_status(url, title, markdown, status):
    """Updates a specific URL with its crawled content."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE gov_bd_pages 
        SET title = %s, markdown_body = %s, status = %s, crawled_at = CURRENT_TIMESTAMP
        WHERE url = %s;
    """, (title, markdown, status, url))
    conn.commit()
    cursor.close()
    conn.close()

def get_pending_urls():
    """Retrieves a list of all URLs currently marked as pending."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM gov_bd_pages WHERE status = 'pending';")
    urls = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return urls