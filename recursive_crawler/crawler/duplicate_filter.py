import pandas as pd
import glob

# --- Configuration ---
# Replace 'url' with the actual column name in your CSV files that contains the URLs
URL_COLUMN_NAME = 'Link' 

# Path to your main 39k CSV file
main_csv_path = 'crawled_alive_sites.csv'

# Path pattern to match your 8 verified CSV files (e.g., all csvs in a 'verified' folder)
verified_csv_pattern = 'govbddir/*.csv' 

# Path to save the final filtered output
output_csv_path = 'filtered_urls.csv'
# ---------------------

def filter_verified_urls():
    # 1. Load the main CSV
    print(f"Loading main CSV: {main_csv_path}")
    main_df = pd.read_csv(main_csv_path,encoding_errors='replace')
    
    initial_count = len(main_df)
    print(f"Initial URL count: {initial_count}")

    # 2. Load all verified CSVs and collect the URLs into a set
    verified_urls = set()
    verified_files = glob.glob(verified_csv_pattern)
    
    if not verified_files:
        print("No verified CSV files found. Please check your path pattern.")
        return

    print(f"Found {len(verified_files)} verified CSV files. Processing...")
    
    for file in verified_files:
        try:
            temp_df = pd.read_csv(file,encoding_errors='replace')
            if URL_COLUMN_NAME in temp_df.columns:
                # Add the URLs to our set (using a set makes lookups O(1) and automatically handles duplicates)
                verified_urls.update(temp_df[URL_COLUMN_NAME].dropna().astype(str).tolist())
            else:
                print(f"Warning: Column '{URL_COLUMN_NAME}' not found in {file}")
        except Exception as e:
            print(f"Error reading {file}: {e}")

    print(f"Total unique verified URLs collected: {len(verified_urls)}")

    # 3. Filter the main DataFrame
    # Keep rows where the URL is NOT in the verified_urls set
    filtered_df = main_df[~main_df[URL_COLUMN_NAME].astype(str).isin(verified_urls)]
    
    final_count = len(filtered_df)
    print(f"Filtered URL count: {final_count}")
    print(f"Removed {initial_count - final_count} already verified URLs.")

    # 4. Save the result to a new CSV
    filtered_df.to_csv(output_csv_path, index=False)
    print(f"Saved filtered dataset to: {output_csv_path}")

if __name__ == "__main__":
    filter_verified_urls()