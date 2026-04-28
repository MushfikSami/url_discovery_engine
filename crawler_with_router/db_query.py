import psycopg2

# ==========================================
# CONFIGURATION
# ==========================================
DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

OUTPUT_FILE = "data/query_results.txt"

def export_query_to_text(query, output_filename):
    print(f"[*] Executing query...")
    
    try:
        # Connect to the database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Execute the provided SQL query
        cursor.execute(query)
        
        # Extract column headers
        column_headers = [desc[0] for desc in cursor.description]
        
        # Open the text file in write mode with UTF-8 encoding
        with open(output_filename, 'w', encoding='utf-8') as f:
            
            # Write the headers separated by a pipe (|)
            f.write(" | ".join(column_headers) + "\n")
            f.write("-" * 80 + "\n")
            
            # Fetch all rows and write them to the file
            rows_written = 0
            for row in cursor.fetchall():
                # Convert each item to a string, replacing NULLs with 'NULL'
                formatted_row = " | ".join(str(item) if item is not None else "NULL" for item in row)
                f.write(formatted_row + "\n")
                rows_written += 1
                
        print(f"[+] Successfully exported {rows_written} rows to {output_filename}")
        
    except Exception as e:
        print(f"[!] Database Error: {e}")
        
    finally:
        # Ensure connections are closed safely
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

# ==========================================
# EXECUTION
# ==========================================
if __name__ == "__main__":
    # Insert your specific SQL query here
    sample_query = """
        SELECT * from crawled_data order by url desc limit 5;
    """
    
    export_query_to_text(sample_query, OUTPUT_FILE)