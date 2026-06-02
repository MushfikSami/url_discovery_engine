
## 🌐 Base URL

```text
https://admin.portal.gov.bd

```

> **Note:** Connections require disabling strict SSL verification (`verify=False` in Python) to bypass local issuer certificate blocks common on this infrastructure.

---

## 🗺️ Complete Endpoint Registry

### 1. Ministry Hierarchy Endpoints

Used to crawl the top-level macro structure of the Bangladesh government organization tree.

* ### `GET /api/e-directory/all-ministry`


* **Purpose:** Fetches all top-level ministries.
* **Query Parameters:** None.
* **Key Fields Returned:** `_id`, `name_bn`, `name_en`, `subdomain`.


* ### `GET /api/e-directory/child-ministry`


* **Purpose:** Fetches sub-ministries, directorates, or departments attached to a parent ministry.
* **Query Parameters:**
* `id` *(string, Required)*: The `_id` of the parent ministry.


* **Key Fields Returned:** Hierarchical sub-office trees.



---

### 2. Field Office Geo-Location Endpoints

Used to traverse regional administrative tiers when looking up field offices.

* ### `GET /api/e-directory/office-list/division`


* **Query Parameters:** `domain` *(string)*


* ### `GET /api/e-directory/office-list/district`


* **Query Parameters:** `domain` *(string)*


* ### `GET /api/e-directory/office-list/upazila`


* **Query Parameters:** `domain` *(string)*


* ### `GET /api/e-directory/office-list/union`


* **Query Parameters:** `domain` *(string)*



---

### 3. Personnel Data Endpoints

The target layer containing structured entity details optimized for your Elasticsearch ingestion pipeline.

* ### `GET /api/e-directory/officer-list`


* **Purpose:** Pulls complete rosters of personnel matching a specific domain or office.
* **Query Parameters:**
* `domain` *(string, Required)*: e.g., `mopa.gov.bd`
* `page` *(integer)*: Page number for pagination.
* `limit` *(integer)*: Number of rows per request.


* **Payload Schema:** Returns a grouped object structured by `category_name` containing an array of `officers`.


* ### `GET /api/e-directory/search-officers`


* **Purpose:** Global flat search across personnel names and designations.
* **Query Parameters:**
* `search_key` *(string, Required)*: Search phrase or keyword (Bengali or English).
* `page` *(integer)*: Page number.
* `limit` *(integer)*: Records per page.





---

## 📊 Document Data Schema Map

When targeting the personnel layers, these are the deterministic data parameters available to your dictionary mapper and index templates:

| Field Name | Type | Description | Optimization Strategy |
| --- | --- | --- | --- |
| `_id` / `id` | String | Unique hash tracking the record | Document `_id` in Elasticsearch |
| `name_bn` / `title_bn` | String | Officer name in Bengali | Analyze with **Native Bengali Analyzer** |
| `name_en` / `title_en` | String | Officer name in English | Standard English analyzer |
| `designation_bn` | String | Official role description in Bengali | Analyze with **Native Bengali Analyzer** |
| `designation_en` | String | Official role description in English | Standard English analyzer |
| `mobile` | String | Mobile contact number | Keyword type (remove leading whitespace) |
| `email` | String | Official email address | Keyword type / lowercase normalizer |
| `phone_office` | String | Office desk phone number | Keyword type |
| `subdomain` / `uploaddomain` | String | Source domain entity mapping | Keyword type (useful for tree filtering) |
| `org_name_bn` | String | Associated organization name in Bengali | Index as Entity-based term |
| `category_name` | String | Department branch identifier within office | Index as Entity-based term |
| `photo` | String | Fully qualified Oracle Cloud CDN storage URL | Store only (disable indexing) |
| `sort_order` | String/Int | Administrative sorting weight | Integer type for custom search ranking |