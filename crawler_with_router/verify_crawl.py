import psycopg2
import textwrap
import sys

# Database configuration
DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def inspect_url(target_url, columns):
    print(f"\n🔍 Querying database for: {target_url}")
    print("=" * 60)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Check the queue status first
        cursor.execute("SELECT status, added_at FROM spider_queue WHERE url LIKE %s;", (target_url,))
        queue_result = cursor.fetchone()
        
        if queue_result:
            status, added_at = queue_result
            print(f"🚦 QUEUE STATUS : {status.upper()} (Added: {added_at})")
        else:
            print("🚦 QUEUE STATUS : NOT FOUND in spider_queue")
            
        # 2. Dynamically construct the query for crawled_data
        # We always fetch lengths of the markdown to verify payload size without printing it all
        safe_columns = [col for col in columns if col in ['url', 'raw_markdown', 'snippet', 'keywords']]
        
        if not safe_columns:
            print("⚠️ No valid columns selected for crawled_data.")
            return

        query_cols = ", ".join(safe_columns)
        
        cursor.execute(f"""
            SELECT LENGTH(raw_markdown), {query_cols} 
            FROM crawled_data 
            WHERE url LIKE %s;
        """, (target_url,))
        
        data_result = cursor.fetchone()
        
        if data_result:
            markdown_length = data_result[0]
            print(f"📦 PAYLOAD SIZE : {markdown_length} characters")
            print("-" * 60)
            
            # Print the dynamically requested columns
            # data_result[1:] contains the requested columns in order
            for col_name, value in zip(safe_columns, data_result[1:]):
                print(f"\n[ {col_name.upper()} ]")
                
                if not value:
                    print("  -> NULL or EMPTY")
                    continue
                    
                if isinstance(value, list):
                    # Handle arrays (like keywords)
                    print(f"  -> {', '.join(value)}")
                elif col_name == 'raw_markdown':
                    # Truncate raw markdown to prevent terminal flooding
                    preview = value[:500] + "\n\n... [TRUNCATED] ..." if len(value) > 500 else value
                    print(textwrap.indent(preview, '  '))
                else:
                    # Handle text (like snippet)
                    wrapped_text = textwrap.fill(str(value), width=80)
                    print(textwrap.indent(wrapped_text, '  '))
                    
        else:
            print("\n⚠️ NO EXTRACTED DATA: This URL has not been successfully saved to crawled_data yet.")
            
    except Exception as e:
        print(f"\n❌ Database Error: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    print("🕸️  GovBD Manual Database Inspector")
    print("-" * 40)
    
    url_input = input("Enter exact URL (or use % as wildcard): ").strip()
    
    print("\nAvailable columns: url, raw_markdown, snippet, keywords")
    cols_input = input("Enter columns to view (comma separated) [Default: snippet,keywords]: ").strip()
    
    if not cols_input:
        columns_to_check = ['snippet', 'keywords']
    else:
        columns_to_check = [c.strip().lower() for c in cols_input.split(',')]
        
    inspect_url(url_input, columns_to_check)