# config.py

# File Paths
DATASET_PATH = "v4_data.csv"

# Elasticsearch Settings
ES_HOST = "http://localhost:9200"
INDEX_NAME = "gov_entity_data"

VLLM_API_BASE= "http://localhost:5000/v1"  # <-- Base URL for VLLM API (if needed for future phases)

# Test Variables
TEST_SEARCH_QUERY = "এসএসসির সনদ হারিয়ে গেলে কীভাবে তুলব?"  # <-- A sample Bengali query to test retrieval speed