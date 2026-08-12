"""
rnd_token_stats.py
==================

R&D: LLM token-size distribution of crawled content, measured with the *exact*
tokenizer of the deployed model (Qwen3.6, served by vLLM as `qwen36` /
`cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit`). These are true LLM tokens -- NOT embedding
tokens and NOT a tiktoken approximation. The local tokenizer's counts were
verified to match the live vLLM `/tokenize` endpoint.

Two analyses, each producing a per-row token count and full distribution stats:

  A. crawled_data.raw_markdown        -- the page's HTML-derived markdown
                                         (post-migration: OCR text removed)
  B. crawled_data_ocr.ocr_markdown    -- OCR text extracted from a page's PDFs

Output: writes rnd_token_stats.json (summary stats + histogram) consumed by the
dataviz report. Raw per-row counts are also saved for reproducibility.
"""

import json
import os
import warnings

import numpy as np
import psycopg2
from tqdm import tqdm
from transformers import AutoTokenizer

warnings.filterwarnings("ignore")

os.environ.setdefault("HF_HOME", os.path.join(os.path.dirname(__file__), ".hf_cache"))

DB_CONFIG = {
    "dbname": "gov_spider_db",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": "5432",
}
MODEL_REPO = "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"
OUT_JSON = "rnd_token_stats.json"
FETCH_BATCH = 2000  # server-side cursor page size

print("[*] Loading Qwen3.6 tokenizer (exact match to vLLM server)...")
TOK = AutoTokenizer.from_pretrained(MODEL_REPO, trust_remote_code=True)


def count_tokens(text: str) -> int:
    if not text:
        return 0
    # add_special_tokens=False -> pure content tokens, matching the /tokenize
    # endpoint used to validate this tokenizer.
    return len(TOK.encode(text, add_special_tokens=False))


def stream_token_counts(query: str, total: int, label: str):
    """Iterate rows with a server-side cursor so we never load the whole table
    into RAM, tokenizing each row's text. Returns a numpy array of counts."""
    conn = psycopg2.connect(**DB_CONFIG)
    counts = []
    empties = 0
    try:
        # Named cursor => server-side, streamed in FETCH_BATCH chunks.
        cur = conn.cursor(name=f"rnd_{label}")
        cur.itersize = FETCH_BATCH
        cur.execute(query)
        for (text,) in tqdm(cur, total=total, desc=f"Tokenizing {label}"):
            n = count_tokens(text)
            counts.append(n)
            if n == 0:
                empties += 1
        cur.close()
    finally:
        conn.close()
    return np.array(counts, dtype=np.int64), empties


def row_count(table: str, where: str = "") -> int:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT count(*) FROM {table} {where};")
        return cur.fetchone()[0]
    finally:
        conn.close()


def summarize(counts: np.ndarray, empties: int) -> dict:
    """Full distribution summary for a token-count array."""
    nonzero = counts[counts > 0]
    pcts = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    percentiles = {f"p{p}": float(np.percentile(counts, p)) for p in pcts}

    # Histogram on a log-ish set of human-readable bins (tokens).
    bin_edges = [0, 100, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000,
                 float(max(counts.max(), 64001))]
    hist, edges = np.histogram(counts, bins=bin_edges)
    histogram = [
        {"lo": int(edges[i]), "hi": int(edges[i + 1]), "count": int(hist[i])}
        for i in range(len(hist))
    ]

    return {
        "n_rows": int(counts.size),
        "n_empty": int(empties),
        "total_tokens": int(counts.sum()),
        "mean": float(counts.mean()),
        "std": float(counts.std(ddof=1)) if counts.size > 1 else 0.0,
        "min": int(counts.min()),
        "max": int(counts.max()),
        "median": float(np.median(counts)),
        "mean_nonzero": float(nonzero.mean()) if nonzero.size else 0.0,
        "std_nonzero": float(nonzero.std(ddof=1)) if nonzero.size > 1 else 0.0,
        "cv": float(counts.std(ddof=1) / counts.mean()) if counts.mean() else 0.0,
        "percentiles": percentiles,
        "histogram": histogram,
    }


def main():
    results = {
        "tokenizer": MODEL_REPO,
        "tokenizer_class": TOK.__class__.__name__,
        "note": "True Qwen3.6 LLM tokens (validated against vLLM /tokenize). "
                "Not embedding tokens.",
    }

    # ---- Analysis A: crawled_data.raw_markdown ------------------------------
    total_a = row_count("crawled_data")
    counts_a, empt_a = stream_token_counts(
        "SELECT raw_markdown FROM crawled_data", total_a, "raw_markdown"
    )
    results["raw_markdown"] = summarize(counts_a, empt_a)

    # ---- Analysis B: crawled_data_ocr.ocr_markdown --------------------------
    total_b = row_count("crawled_data_ocr")
    counts_b, empt_b = stream_token_counts(
        "SELECT ocr_markdown FROM crawled_data_ocr", total_b, "ocr_markdown"
    )
    results["ocr_markdown"] = summarize(counts_b, empt_b)

    # Save raw counts for reproducibility / re-plotting.
    np.save("rnd_counts_raw_markdown.npy", counts_a)
    np.save("rnd_counts_ocr_markdown.npy", counts_b)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # ---- Console summary ----------------------------------------------------
    for key in ("raw_markdown", "ocr_markdown"):
        s = results[key]
        print(f"\n=== {key} ===")
        print(f"  rows           : {s['n_rows']:,}  (empty: {s['n_empty']:,})")
        print(f"  total tokens   : {s['total_tokens']:,}")
        print(f"  mean ± std     : {s['mean']:.1f} ± {s['std']:.1f}  (CV={s['cv']:.2f})")
        print(f"  median         : {s['median']:.1f}")
        print(f"  min / max      : {s['min']:,} / {s['max']:,}")
        print(f"  p90 / p95 / p99: {s['percentiles']['p90']:.0f} / "
              f"{s['percentiles']['p95']:.0f} / {s['percentiles']['p99']:.0f}")
    print(f"\n[+] Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
