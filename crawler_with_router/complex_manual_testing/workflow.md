# Complex Manual Testing Workflow

## Overview

This directory contains a **manual inspection and diagnostic system** for testing URL parsing pipelines against real-world government website data (primarily Bengali language government portals). It evaluates how different parsing strategies handle complex web pages and validates the router logic that decides between fast static parsing and heavy browser-based extraction.

---

## Purpose

The manual testing framework serves to:

- **Validate Router Logic**: Test the decision-making system that routes URLs between two parsing strategies
- **Diagnose Parsing Failures**: Manually inspect URLs that may be problematic or require special handling
- **Quality Assurance**: Generate detailed reports on what content was extracted from each page
- **Performance Analysis**: Compare results between fast parsing (Markdownify) and heavy browser parsing (Crawl4AI)

---

## System Architecture

### Core Components

1. **manual_tester.py** - Main testing orchestrator
   - Fetches sample URLs from the `spider_queue` database table
   - Runs diagnostic evaluation on each URL
   - Generates markdown inspection reports
   - Implements router decision logic

2. **manual_inspections/** - Output directory
   - Contains 5+ inspection reports (one per URL tested)
   - Each report is a markdown file with extracted content and metadata

3. **Dependencies**
   - `extractor.py` - Content extraction utilities (keyword extraction, JS detection)
   - `parsers.py` - Dual parsing implementations (Crawl4AI and Markdownify)
   - `db_setup.py` - Database configuration for spider_queue access

---

## Workflow Steps

### Step 1: Sample Selection
```
fetch_sample_urls(limit=5) → Retrieves 5 random URLs from spider_queue table
```
- Queries PostgreSQL `spider_queue` table with `RANDOM()` ordering
- Returns: `(url, base_domain, status)` tuples
- Used for quick, representative testing

### Step 2: Router Decision Logic
For each URL, the system evaluates three decision factors:

#### Factor A: Stubborn Domain Rule
```python
STUBBORN_DOMAINS = [
    'beza.gov.bd',
    'planningcommission.gov.bd',
    'landadministration.gov.bd'
]
```
- Forces **heavy browser mode** (Crawl4AI) for known problematic domains
- These domains require JavaScript execution for proper rendering

#### Factor B: JavaScript Detection
```
is_javascript_heavy(soup) → Boolean
```
- Scans HTML structure for JS rendering indicators
- Detects frameworks like Vue.js, Angular, React patterns
- Heavy JS content requires browser execution

#### Factor C: Table Complexity Analysis
```
analyze_table_complexity(soup, html_content) → (is_complex: bool, reason: str)
```

**Heuristic 1: Tabular Layout Density**
- Triggers if: `table_count > 3` OR `tr_count > 20`
- Example: Pages with extensive data tables need proper rendering

**Heuristic 2: Dynamic Table Framework Detection**
- Searches for framework signatures in HTML:
  - `datatable`, `gridview`, `tbody`
  - `v-data-table`, `ngx-datatable`, `ag-grid`, `handsontable`
- Indicates client-side rendering; requires browser execution

### Step 3: Routing Decision
```
use_heavy_browser = force_headless OR is_js_heavy OR is_complex_table
```

**Route 1: HEAVY BROWSER (Crawl4AI)**
- Used when: URL matches stubborn domains, JS-heavy, or table complexity detected
- Slower (~5-10s per page) but handles dynamic content
- Returns fully rendered markdown

**Route 2: FAST STATIC (Markdownify)**
- Used when: Standard HTML composition with minimal JS
- Fast (~1-2s per page)
- Direct HTML → Markdown conversion

### Step 4: Content Extraction
```
markdown = parse_with_crawl4ai(url) OR parse_with_markdownify(html_content)
```
- Converts HTML to structured markdown
- Extracts keywords for indexing
- Generates snippets for search results

### Step 5: Content Verification
Three-level validation:

**Level 1: Non-Empty Check**
```
if not markdown:
    → FAILED: Payload generation failed completely
```

**Level 2: Captcha/Blocked Detection**
```
if "just a moment" in markdown OR "cloudflare" in markdown:
    → FAILED: Page behind captcha/WAF wall
```

**Level 3: Payload Size Warning**
```
if len(markdown) < 50 chars:
    → WARNING: Micro-payload (possible content extraction issue)
else (len >= 50):
    → PASSED: Valid content extracted
```

### Step 6: Report Generation
Creates markdown inspection file with structure:

```markdown
# MANUAL INSPECTION REPORT
- **URL**: [original_url]
- **Routing Logic Implemented**: [Crawl4AI | Markdownify]
- **Complexity Profile**: [table_complexity_reason]
- **Extracted Keywords**: [keyword_list]

================================================================

[Full extracted markdown content]
```

**Filename Pattern**: `inspect_XX_[sanitized_url].md`
- Index: Zero-padded (01, 02, 03, etc.)
- URL: Domain and path, max 40 chars, special chars replaced with `_`
- Example: `inspect_01_mes_portal_gov_bd_pages_officers.md`

---

## Output Structure

```
complex_manual_testing/
├── manual_tester.py
├── workflow.md (this file)
└── manual_inspections/
    ├── inspect_01_mes_portal_gov_bd_pages_officers.md
    ├── inspect_02_dss_gov_bd_pages_static-pages_6922dd6b93.md
    ├── inspect_03_biman_gov_bd_pages_officers____-_____-.md
    ├── inspect_04_fri_gov_bd_pages_officers__-________-.md
    └── inspect_05_moha_gov_bd_pages_go-ultimates.md
```

Each inspection file contains:
- Metadata (URL, routing choice, complexity analysis)
- Extracted keywords for validation
- Full rendered content from the parser
- Suitable for manual review and quality assessment

---

## Execution Flow

### Interactive Mode
```
1. Script starts → Loads 5 URLs from spider_queue
2. For each URL:
   a. Fetch raw HTML
   b. Analyze complexity/JS/domain rules
   c. Route to appropriate parser
   d. Verify extracted content
   e. Save inspection report
3. After each URL (except last):
   → Prompt user: "Press Enter to continue or 'q' to quit"
4. Complete → Display summary with output directory path
```

### Database Dependency
- Requires PostgreSQL connection via `db_setup.DB_CONFIG`
- Must have populated `spider_queue` table with URLs
- Table schema: `(url, base_domain, status, ...)`

---

## Key Metrics & Insights

### Router Performance Indicators

| Signal | Indicates | Action |
|--------|-----------|--------|
| Stubborn domain match | Known problematic source | Force heavy browser |
| JS framework detected | Client-side rendering | Use Crawl4AI |
| High table count (>3) | Data-intensive layout | Use Crawl4AI |
| High row count (>20) | Large data tables | Use Crawl4AI |
| Dynamic framework tag | Modern data table | Use Crawl4AI |
| Standard HTML + low JS | Simple content | Use Markdownify |

### Validation Results

- **PASSED**: Content length ≥50 chars, no captcha/cloudflare, valid extraction
- **WARNING**: Micro-payload (<50 chars), possible extraction issues
- **FAILED**: Zero-length payload or content blocked by WAF/captcha

---

## Typical Use Cases

1. **Testing New Domains**
   - Add domain to `STUBBORN_DOMAINS` list if it requires special handling
   - Run manual tester to verify router behavior

2. **Diagnosing Parsing Failures**
   - Review inspection report to see which route was chosen
   - Check extracted content and keywords for data loss
   - Compare Crawl4AI vs Markdownify results

3. **Performance Tuning**
   - Monitor which URLs trigger heavy browser mode
   - Optimize thresholds (table count, JS detection, etc.)
   - Balance speed vs accuracy for the dataset

4. **Content Quality Assurance**
   - Verify keywords are properly extracted
   - Ensure no Cloudflare/captcha walls in output
   - Validate markdown formatting integrity

---

## Integration with Main Pipeline

This manual testing system feeds insights back into:

- **Router Configuration**: Refine decision thresholds and domain lists
- **Extractor Improvements**: Enhance keyword extraction and JS detection
- **Parser Selection**: Validate Crawl4AI vs Markdownify performance
- **Database Quality**: Identify problematic URLs for further investigation

---

## Example Inspection Report

```markdown
# MANUAL INSPECTION REPORT
- **URL**: https://mes.portal.gov.bd/pages/officers/গোবিন্দ-চক্রবর্তী-05d931-6922df2d933eb65569e20647
- **Routing Logic Implemented**: Markdownify
- **Complexity Profile**: Standard text/layout composition.
- **Extracted Keywords**: ['pages', 'officers', 'আর্মি', 'filters', ...]

============================================================

[Extracted markdown content with full page structure]
```

This shows:
- Simple domain → Markdownify chosen
- Standard profile → No complexity triggers
- Successful extraction → Multiple keywords indexed
- Output ready for vector database ingestion

---

## Notes & Maintenance

- **Database Connection**: Ensure PostgreSQL is accessible and spider_queue is populated
- **File Permissions**: Output directory `manual_inspections/` created automatically
- **Async Execution**: Uses asyncio for concurrent HTTP requests (15s timeout per URL)
- **Encoding**: All files saved in UTF-8 to support Bengali language content
- **Interactive Prompts**: Press Enter to continue or 'q' to quit between evaluations
