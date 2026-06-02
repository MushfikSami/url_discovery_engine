# Bangladesh eDirectory API Extractor

## Overview

This module is a lightweight Python data ingestion tool designed to fetch official government directory data directly from the backend REST API powering the Bangladesh National Portal mobile app.

By bypassing the legacy web frontend and circumventing local SSL certificate restrictions, this script retrieves clean, perfectly formatted JSON data. This structured output is highly optimized for the initial ingestion phase, providing raw Bengali text that is ready to be mapped and fed directly into an Elasticsearch cluster utilizing a Native Bengali Analyzer for high-speed, entity-based search.

## Features

* **Direct API Access:** Bypasses messy HTML scraping by utilizing the hidden `admin.portal.gov.bd` mobile endpoint extracted from the compiled Flutter binary.
* **SSL Verification Bypass:** Configured via `urllib3` to safely ignore local issuer certificate blocks (`unable to get local issuer certificate`) common in government infrastructure.
* **Structured JSON Output:** Extracts and saves hierarchical data (Ministries, Subdomains, IDs) directly into a `.json` file, ready for downstream processing and tree-based indexing.

## Prerequisites

* Python 3.8+
* `requests` library

## Installation

1. Navigate to your crawler directory:
```bash

```



cd ~/url_discovery_engine/edirectory_crawler/

```
2. Ensure your virtual environment is active and install the required dependencies:
   ```bash
pip install requests urllib3

```

## Usage

Run the script directly from your terminal:

```bash
python edirectory_fetcher.py

```

### Expected Output

Upon a successful run, the script will output the connection status, print a brief preview of the data, and generate a new file:

* `bd_ministries_clean.json`

```text
🚀 Fetching data from: https://admin.portal.gov.bd/api/e-directory/all-ministry
✅ HTTP 200 OK: Successfully connected to the API!
💾 Saved 62 ministry records to 'bd_ministries_clean.json'

📊 Data Preview:
  1. Ministry of Public Administration | জনপ্রশাসন মন্ত্রণালয় | mopa.gov.bd
  2. Ministry of Textiles & Jute | বস্ত্র ও পাট মন্ত্রণালয় | motj.gov.bd
  ... and more!

```

## Next Steps / Extensibility

The generated JSON file contains the `_id` and `subdomain` for every top-level ministry. This script can be easily extended to loop through these IDs and hit the subsequent nested endpoints (e.g., `/api/e-directory/child-ministry`) to recursively crawl and index the entire 45,000+ organization hierarchy.

## Disclaimer

This script is intended for data ingestion and indexing of publicly available government directory information. Ensure that your automated polling frequency respects the target server's rate limits to maintain optimal response times.