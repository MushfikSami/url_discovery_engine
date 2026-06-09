
# 📊 Dataset Audit & Remediation Strategy Report

## Part 1: Report on Current Dataset Lackings

Based on the programmatic audit, the dataset suffers from three major categories of degradation that are preventing the chatbot from reaching production quality.

### 1. The "Fact vs. Intent" Imbalance

Your dataset currently reads like a textbook rather than a conversational knowledge base.

* **The Flaw:** High-volume categories (like Emergency Certificates, Vehicle Licensing, and Land Services) have hundreds of rows, but they are entirely flat. They state facts but do not answer natural user questions.
* **The Missing Intents:** The chatbot cannot handle conversational logic. There is a near 0% coverage of **"Why" (কেন)** queries across the dataset. If a user asks a troubleshooting question (e.g., "Why was my trade license rejected?" or "Why is the NID server showing an error?"), the bot will fail.

### 2. Underrepresented High-Value Sectors

Annotators have clustered their efforts on "easy" or common categories while completely ignoring critical, complex government services.

* **Severely Lacking:** SME Information (1 row), Land Development Tax (1 row), Expatriate Legal Assistance (1 row), Public Safety (1 row), and Hajj Services (1 row).

### 3. Structural & Metadata Decay

The physical formatting of the CSV is confusing the retrieval engine (RAG system).

* **Missing Identifiers:** Over 50% of the data lacks a `Passage ID`, and 72 rows are missing source `URLs`.
* **Token Bloat:** Nearly 30% of the text blocks contain excessive spacing (3 to 10 consecutive newlines). This wastes the LLM's context window and degrades response generation.
* **Topic Collision:** Multiple rows have the exact same `Topic` name but different text. The bot does not know which one is the "correct" truth.

---

## Part 2: Next Directions for the Annotation Team

To mitigate these issues, divide your 20-person team into specialized task forces and enforce the following strict rules for the next data sprint.

### Directive 1: The "One Intent, One Row" Rule

Annotators must stop copying and pasting massive paragraphs from government websites into a single row.

* **Action:** Break large texts down. If a webpage explains what a Trade License is, how to get it, and how much it costs, that must be **THREE separate rows** in the dataset:
1. *Topic:* ট্রেড লাইসেন্স কী এবং কাদের এটি প্রয়োজন? (What & Who)
2. *Topic:* ট্রেড লাইসেন্স করার আবেদন পদ্ধতি কীভাবে কাজ করে? (How)
3. *Topic:* ট্রেড লাইসেন্স করতে কত টাকা ফি লাগে? (Cost)



### Directive 2: The "Troubleshooting" Mandate

Assign 5 annotators strictly to generate "Edge Case" and "Troubleshooting" data. Users rarely ask bots when things go perfectly; they ask bots when things go wrong.

* **Action:** For every service, annotators MUST create scenarios for:
* Rejections ("কেন আমার আবেদন বাতিল হতে পারে?")
* Corrections ("নাম ভুল আসলে কীভাবে সংশোধন করব?")
* Loss/Recovery ("হারিয়ে গেলে করণীয় কী?")



### Directive 3: Strict Formatting Protocol

* **No whitespace padding:** All paragraphs must be separated by a *single* newline character (`\n`), never multiple.
* **No orphaned data:** A row is invalid and will be rejected if it does not have a `Category`, `Sub-Category`, `Passage ID` (if applicable to your DB structure), and `URL`.
* **Conversational Topics:** The `Topic` column must be written as a natural human question, not a file directory name.
* *Bad:* পাসপোর্ট নবায়ন প্রক্রিয়া।
* *Good:* আমার পাসপোর্টের মেয়াদ শেষ হয়ে গেলে কীভাবে নবায়ন করব?



---

## Part 3: The Universal "360-Degree" Service Schema

To ensure every single government service has maximum coverage, enforce this schema. Before an annotator can mark a service as "Complete", they must ensure they have generated QA pairs for **all 5 tiers** of this schema.

### 🏛️ Universal Schema for Government Services

#### Tier 1: Core Definition & Eligibility (What / Who)

* **What is it?** (Description of the service/certificate).
* **Who needs it?** (Target demographic, mandatory vs. optional).
* **Eligibility Criteria:** (Age limits, citizenship requirements, business types).
* *Example:* ই-টিআইএন (e-TIN) কী এবং কাদের জন্য এটি করা বাধ্যতামূলক?

#### Tier 2: Procedural Logistics (How / Where / When)

* **Application Process:** (Step-by-step online or offline procedure).
* **Required Documents:** (Exact list of papers, photos, attestations needed).
* **Location/Platform:** (Which website, which physical office, which app).
* **Timelines:** (How many days/weeks it takes to process).
* *Example:* নতুন ই-পাসপোর্টের জন্য অনলাইনে কীভাবে আবেদন করতে হয়?

#### Tier 3: Financial Logistics (Cost)

* **Fees & Charges:** (Exact amount, VAT inclusion, normal vs. urgent delivery fees).
* **Payment Methods:** (A-challan, bKash, Bank draft, cash).
* *Example:* জমির নামজারি (Mutation) করতে সরকারি ফি কত টাকা এবং কীভাবে জমা দিতে হয়?

#### Tier 4: Modifications & Renewals (Updates)

* **Renewal Process:** (When and how to renew expired documents).
* **Information Correction:** (Process for fixing spelling mistakes, address changes).
* *Example:* জাতীয় পরিচয়পত্রে (NID) নিজের নামের বানান ভুল থাকলে তা সংশোধনের উপায় কী?

#### Tier 5: Troubleshooting & Support (Why / What if)

* **Rejection Reasons:** (Common reasons the application gets denied).
* **Lost/Stolen Protocol:** (How to get a duplicate copy, GD requirements).
* **Status Checking:** (How to track the application status via SMS/Web).
* **Helplines:** (Official call center numbers or support emails).
* *Example:* আমার জন্ম নিবন্ধন আবেদন বাতিল হলে এখন আমার করণীয় কী?

### Implementation Plan for the Team Lead:

1. **Wipe out duplicates:** Have 2 people run through the existing CSV and delete or merge the duplicate `Topic` rows.
2. **Assign by Schema, Not by Sector:** Instead of saying "Annotator A, do Passports," say "Annotator A, do Tier 4 and Tier 5 (Troubleshooting & Renewals) for Passports, NID, and Land." This forces them to think about edge cases rather than just copying basic procedures.