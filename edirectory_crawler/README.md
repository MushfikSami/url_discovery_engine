# Bangladesh eDirectory API Extractor

## Overview

This module is a lightweight Python data ingestion tool designed to fetch official government directory data directly from the backend REST API powering the Bangladesh National Portal mobile app.

By bypassing the legacy web frontend and circumventing local SSL certificate restrictions, this script retrieves clean, perfectly formatted JSON data. This structured output is highly optimized for the initial ingestion phase, providing raw Bengali text that is ready to be mapped and fed directly into an Elasticsearch cluster utilizing a Native Bengali Analyzer for high-speed, entity-based search.

## Features

- **Direct API Access**: Bypasses messy HTML scraping by utilizing the hidden `admin.portal.gov.bd` mobile endpoint extracted from the compiled Flutter binary.
- **SSL Verification Bypass**: Configured via `urllib3` to safely ignore local issuer certificate blocks (`unable to get local issuer certificate`) common in government infrastructure.
- **Structured JSON Output**: Extracts and saves hierarchical data (Ministries, Subdomains, IDs) directly into a `.json` file, ready for downstream processing and tree-based indexing.

## Project Structure

```
edirectory_crawler/
├── edirectory_fetcher.py      # Main Python script for API data extraction
├── edirectory.xapk            # Android APK (source of API endpoint discovery)
├── bd_ministries_clean.json   # Generated JSON output file
└── README.md                  # This documentation file
```

## Prerequisites

- Python 3.8+
- `requests` library
- `urllib3` library

## Installation

1. Navigate to your crawler directory:

```bash
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

- `bd_ministries_clean.json`

```text
🚀 Fetching data from: https://admin.portal.gov.bd/api/e-directory/all-ministry
✅ HTTP 200 OK: Successfully connected to the API!
💾 Saved 62 ministry records to 'bd_ministries_clean.json'

📊 Data Preview:
  1. Ministry of Public Administration | জনপ্রশাসন মন্ত্রণালয় | mopa.gov.bd
  2. Ministry of Textiles & Jute | বস্ত্র ও পাট মন্ত্রণালয় | motj.gov.bd
  ... and more!
```

## Data Schema

The generated `bd_ministries_clean.json` file contains the following structure:

```json
{
  "data": [
    {
      "_id": "<unique_identifier>",
      "sitename_en": "<Ministry Name in English>",
      "sitename_bn": "<Ministry Name in Bengali>",
      "subdomain": "<gov.bd subdomain>",
      ...additional_fields
    }
  ]
}
```

### Key Fields

| Field | Description |
|-------|-------------|
| `_id` | Unique identifier for the ministry |
| `sitename_en` | Official name in English |
| `sitename_bn` | Official name in Bengali |
| `subdomain` | Government subdomain (e.g., `mopa.gov.bd`) |

## Architecture

### API Endpoint Discovery

The API endpoint (`/api/e-directory/all-ministry`) was discovered by analyzing the `edirectory.xapk` Android application package. This APK contains the Flutter binary that communicates with the Bangladesh National Portal's backend services.

### Data Flow

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  edirectory  │     │  edirectory      │     │ bd_ministries   │
│    .xapk     │────▶│  _fetcher.py     │────▶│   _clean.json   │
│  (Source)    │     │  (Extractor)     │     │   (Output)      │
└──────────────┘     └──────────────────┘     └─────────────────┘
```

## Next Steps / Extensibility

The generated JSON file contains the `_id` and `subdomain` for every top-level ministry. This script can be easily extended to loop through these IDs and hit the subsequent nested endpoints (e.g., `/api/e-directory/child-ministry`) to recursively crawl and index the entire 45,000+ organization hierarchy.

### Potential Enhancements

- **Recursive Crawling**: Iterate through ministry IDs to fetch nested organization data
- **Rate Limiting**: Add configurable delay between requests to respect server load
- **Error Handling**: Implement retry logic for failed requests
- **Incremental Updates**: Only fetch changed records on subsequent runs
- **Elasticsearch Integration**: Direct pipeline to push data to Elasticsearch

## Disclaimer

This script is intended for data ingestion and indexing of publicly available government directory information. Ensure that your automated polling frequency respects the target server's rate limits to maintain optimal response times.