from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from tree_builder import build_site_tree # Importing the script we just wrote!

# --- Configuration ---
DB_CONFIG = {
    'dbname': 'gov_spider_db',
    'user': 'postgres',
    'password': 'password', # Update this with your actual DB password
    'host': 'localhost',
    'port': '5432'
}

app = FastAPI(title="Gov Spider Site Tree API")

# Enable CORS so your frontend HTML file can talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your actual frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"Database connection failed: {e}")
        return None


@app.get("/api/tree/{domain}")
async def get_domain_tree(domain: str):
    """
    Fetches all URLs for a specific domain from the database
    and returns them as a nested JSON tree structure.
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        with conn.cursor() as cur:
            # Look up the domain in your master index
            cur.execute(
                "SELECT web_pages FROM domain_hierarchy WHERE website = %s;", 
                (f"https://{domain}",) # Assuming your DB stores the full URL protocol
            )
            result = cur.fetchone()

            if not result or not result[0]:
                # Fallback check just in case the DB stores it without https://
                cur.execute(
                    "SELECT web_pages FROM domain_hierarchy WHERE website = %s;", 
                    (domain,)
                )
                result = cur.fetchone()

            if not result or not result[0]:
                raise HTTPException(status_code=404, detail=f"Domain '{domain}' not found in database.")

            url_list = result[0]

            # Pass the flat list to our transformer script
            tree_data = build_site_tree(domain, url_list)
            
            return tree_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/domains")
async def get_all_domains():
    """
    Fetches the master list of all scraped domains for the frontend dropdown.
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        with conn.cursor() as cur:
            # Grab all domains from the hierarchy index
            cur.execute("SELECT website FROM domain_hierarchy;")
            rows = cur.fetchall()
            
            # Clean up the URLs for a beautiful UI (remove https://)
            domains = sorted([row[0].replace("https://", "").replace("http://", "") for row in rows if row[0]])
            
            return {"domains": domains}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()        

# Start instruction:
# uvicorn main:app --reload --host 0.0.0.0 --port 8000