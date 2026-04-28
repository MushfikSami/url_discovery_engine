import pandas as pd
from sqlalchemy import create_engine
import warnings

# Suppress warnings
warnings.filterwarnings('ignore', 'pandas only supports SQLAlchemy connectable')

# ==========================================
# CONFIGURATION
# ==========================================
DB_CONFIG = {
    "dbname": "bd_gov_db", # Update to url_discovery_db if needed
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

SUMMARY_CSV = "db_tables_summary.csv"
SCHEMA_CSV = "db_all_schemas.csv"

def generate_full_db_snapshot():
    print(f"[*] Connecting to database '{DB_CONFIG['dbname']}' to generate full snapshot...\n")
    
    engine_url = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    engine = create_engine(engine_url)
    
    try:
        # 1. Get all table names in the public schema
        query_tables = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public';
        """
        tables = pd.read_sql(query_tables, engine)['table_name'].tolist()
        
        if not tables:
            print("[!] No tables found in the public schema.")
            return

        summary_data = []
        schema_data = []
        
        # 2. Iterate over every table to gather metrics and schema
        for table in tables:
            print(f"[*] Processing table: {table}")
            
            # Get Row Count
            count_query = f'SELECT COUNT(*) FROM "{table}";'
            row_count = pd.read_sql(count_query, engine).iloc[0, 0]
            
            # Get Disk Size
            size_query = f"SELECT pg_size_pretty(pg_total_relation_size('\"{table}\"'));"
            table_size = pd.read_sql(size_query, engine).iloc[0, 0]
            
            summary_data.append({
                "Table Name": table,
                "Total Rows": row_count,
                "Disk Size": table_size
            })
            
            # Get Schema (Columns and Data Types)
            schema_query = f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table}';
            """
            df_schema = pd.read_sql(schema_query, engine)
            
            for _, row in df_schema.iterrows():
                schema_data.append({
                    "Table Name": table,
                    "Column Name": row['column_name'],
                    "Data Type": row['data_type']
                })
                
            # Print a quick terminal summary for this table
            print(f"    -> Rows: {row_count:,} | Size: {table_size}")
            print(f"    -> Columns: {len(df_schema)}")
            print("-" * 40)
            
        # 3. Export to CSVs
        df_summary_out = pd.DataFrame(summary_data)
        df_schema_out = pd.DataFrame(schema_data)
        
        df_summary_out.to_csv(SUMMARY_CSV, index=False, encoding='utf-8')
        df_schema_out.to_csv(SCHEMA_CSV, index=False, encoding='utf-8')
        
        print(f"\n[+] Snapshot complete!")
        print(f"  -> High-level summary saved to: {SUMMARY_CSV}")
        print(f"  -> Detailed schemas saved to:   {SCHEMA_CSV}")

    except Exception as e:
        print(f"\n[!] Error generating full snapshot: {e}")

if __name__ == "__main__":
    generate_full_db_snapshot()