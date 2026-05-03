# Crawler Strategy Guide

## Phase 1: URL & Routing Eradication (The spider_queue Purges)

This phase focused on breaking infinite loops, CMS routing bugs, and blocking massive databases that provided zero value to a generalized LLM.

### 1. The CMS Routing Mutations (The Death Spirals)

**Target:** Savar Municipality (CodeIgniter bug) and SREDA.

**The Filter:** We tracked down frameworks that dynamically generated infinite URL paths. If core structural folders repeated themselves (e.g., `/home/home/`, `/notice/notice/` or SREDA's `/locallab/locallab/`), we vaporized the link.

**Folders Blocked:** `home`, `main`, `notice`, `index.php`, `irsc`, `nem`, `locallab`, `intllab`, `stakeholder`, `login`, `view`, `noc`.

---

### 2. Massive User-Generated Content (UGC) & Social Portals

**Target:** The national Teachers Portal (`teachers.gov.bd`).

**The Filter:** We blocked personal profiles, user-uploaded lesson plans, personal photo galleries, and user success stories to prevent the LLM from learning about individual citizens rather than government policy.

**Paths Blocked:** `/profile/`, `/content/details/`, `/contents/pictures`, `/success-story/details/`, and any URL containing `username=`.

---

### 3. The Infinite Hydras & Deep Directories

**Target:** Bangladesh Scouts (`service.scouts.gov.bd`).

**The Filter:** We severed the massive, infinitely sprouting tree of regional scouting directories that mapped every single unit, group, and member in the country.

**Paths Blocked:** `/group-details/`, `/unit-details/`, and wildcard `/edirectory-`.

---

### 4. Legacy & Highly Specialized Databases

**Target:** Roads and Highways (RHD) Bridge Database, Customs Tariff Matrices, and LIMA Factory Inspections.

**The Filter:** We blocked the crawler from querying legacy `.asp` databases iterating through thousands of bridge inspection years, infinite operative tariff combinations, and tens of thousands of hyper-specific factory safety audits.

**Paths Blocked:** `/BridgeDatabase/`, `/operative-tariff/details/`, `/hs-code-details/`, `/public-report/establishment/`.

---

### 5. Direct Media Ingestion & WordPress Uploads

**Target:** Police News (`news.police.gov.bd`) and general WordPress sites.

**The Filter:** We stopped the spider from directly downloading image binaries that snuck past the initial MIME-type checks by living in raw archive folders.

**Extensions Blocked:** `.jpg`, `.jpeg`, `.png`, and the entire `/wp-content/uploads/` directory.

---

### 6. Infinite Pagination Traps

**Target:** Krishibatighor E-Library.

**The Filter:** We killed query parameters that generated infinite pages regardless of whether content actually existed on them (e.g., Page 23,000+).

**Queries Blocked:** `page_name=ELibrary` combined with `&page=`.

---

## Phase 2: Payload & Semantic Sanitization (The crawled_data Deep Clean)

This phase assumed the URL was legitimate, but investigated the actual downloaded Markdown to ensure the server didn't hand us garbage, errors, or bloat.

### 7. The Exact Duplicate Purge (The Hash Strike)

**The Filter:** Government sites frequently cross-post the exact same memos and holiday notices. We used an MD5 hash window function (`md5(raw_markdown)`) to mathematically prove if two documents were completely identical. We kept the first instance and vaporized all other copies across the entire 2.8 million row database. *(This single filter removed nearly 800,000 redundant pages.)*

---

### 8. Base64 Image Monsters

**The Filter:** We hunted down servers that embedded high-resolution images directly into the HTML as Base64 strings, which the Markdown converter translated into 60-million-character strings of random text (guaranteed to cause Out-Of-Memory crashes for an LLM).

**Rule:** Any document exceeding **500,000 characters** was deleted.

---

### 9. The Empty Shell & Boilerplate Check

**The Filter:** We eradicated pages that successfully returned a 200 OK network status but contained no actual policy data.

**Rules Applied:**
- Deleted any page with less than **50 characters** of total text.
- Deleted pages with placeholder text: *"Under Construction"*, *"Site is being updated"*, or short login prompts.

---

### 10. Disguised Server Errors

**The Filter:** Government servers frequently serve error messages as valid documents. We searched the Markdown for tell-tale error signatures.

**Phrases Blocked:** `"404 Not Found"`, `"Access Denied"`, `"Cloudflare"` (bot-checks), and `"Database connection error"`.

---

### 11. Empty Table Boilerplates

**The Filter:** We removed "Empty State" pages from public notice boards or calendars where the spider crawled a valid link, but the table was devoid of entries.

**Phrases Blocked:** `"No records found"`, `"No data available in table"`, `"No notice found"`, `"No events scheduled"`.

---

### 12. The SEO Defacement Trap

**The Filter:** We found government domains with outdated CMS software that had been compromised by black-hat SEO hackers injecting invisible spam to boost their Google rankings. We deleted these so your LLM wouldn't train on spam.

**Phrases Blocked:** `"casino"`, `"jackpot"`, `"crypto"`, `"viagra"`.

> **Note:** We explicitly whitelisted `ti-bangladesh.org` to ensure we didn't delete legitimate anti-corruption reports.

---

### 13. Mojibake & Encoding Failures

**The Filter:** We tracked down servers that sent the wrong language encoding headers (like Latin-1 instead of UTF-8), which permanently shredded the Bengali text into unreadable symbols.

**Signatures Blocked:**
- `CHR(65533)` — The U+FFFD Unicode Replacement Character / Black Diamonds
- `?????` — Font rendering cascade failures
- `à¦` and `à§` — The phonetic signature of Latin-1 misinterpreting Bengali hex codes

---

### 14. The Orphan Cleanser

**The Filter:** As a final data-integrity sweep, we ran a cross-referencing command to delete any extracted Markdown in `crawled_data` that no longer had a matching, active URL in the cleaned `spider_queue`.
