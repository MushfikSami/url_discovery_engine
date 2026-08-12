"""
rnd_token_report.py
==================

Renders rnd_token_stats.json into a self-contained HTML report
(rnd_token_report.html) following the dataviz design system: sequential blue
(single hue) histograms, KPI stat tiles, a percentile table, light/dark themes
with a toggle, and per-bar hover tooltips.

Two distributions are reported:
  * raw_markdown  (crawled_data)      -- page HTML-derived markdown
  * ocr_markdown  (crawled_data_ocr)  -- OCR text from a page's PDFs

Token counts are true Qwen3.6 LLM tokens (see rnd_token_stats.py).
"""

import json
import html

IN_JSON = "rnd_token_stats.json"
OUT_HTML = "rnd_token_report.html"


def fmt(n, digits=0):
    if isinstance(n, float) and digits == 0:
        n = round(n)
    if isinstance(n, (int,)) or (isinstance(n, float) and digits == 0):
        return f"{int(n):,}"
    return f"{n:,.{digits}f}"


def compact(n):
    """Auto-compact large numbers for stat-tile values: 1,284 / 12.9K / 4.2M."""
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if abs(n) >= 10_000:
        return f"{n/1_000:.1f}K"
    return f"{int(round(n)):,}"


def bin_label(lo, hi, is_last):
    def c(v):
        return compact(v) if v >= 1000 else str(v)
    if is_last:
        return f"{c(lo)}+"
    return f"{c(lo)}–{c(hi)}"


def stat_tiles(s):
    tiles = [
        ("Rows analyzed", compact(s["n_rows"]), f"{fmt(s['n_empty'])} empty"),
        ("Mean tokens / row", compact(s["mean"]), f"± {compact(s['std'])} std"),
        ("Median (p50)", compact(s["median"]), f"CV {s['cv']:.2f}"),
        ("p95", compact(s["percentiles"]["p95"]), f"p90 {compact(s['percentiles']['p90'])}"),
        ("p99", compact(s["percentiles"]["p99"]), f"max {compact(s['max'])}"),
        ("Total tokens", compact(s["total_tokens"]), "whole table"),
    ]
    out = ['<div class="kpi-row">']
    for label, value, sub in tiles:
        out.append(
            f'<div class="tile"><div class="tile-label">{html.escape(label)}</div>'
            f'<div class="tile-value">{html.escape(value)}</div>'
            f'<div class="tile-sub">{html.escape(sub)}</div></div>'
        )
    out.append("</div>")
    return "".join(out)


def histogram_svg(s, chart_id):
    """Vertical column histogram. Single sequential-blue series -> no legend
    (title names it). Recessive gridlines, muted axis, 4px rounded caps, 2px
    surface gaps between columns, per-column hover tooltip, direct-labeled caps."""
    hist = s["histogram"]
    n = len(hist)
    max_count = max(h["count"] for h in hist) or 1

    W, H = 860, 340
    ml, mr, mt, mb = 56, 16, 24, 64
    plot_w = W - ml - mr
    plot_h = H - mt - mb
    slot = plot_w / n
    bar_w = min(24 * 2, slot - 10)  # cap thickness; leftover is air

    # y gridlines at clean fractions of max_count
    def y_of(v):
        return mt + plot_h * (1 - v / max_count)

    ticks = 4
    gridvals = [round(max_count * i / ticks) for i in range(ticks + 1)]

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="Token count histogram">']

    # gridlines + y ticks
    for gv in gridvals:
        y = y_of(gv)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{ml-8}" y="{y+4:.1f}" class="ytick">{fmt(gv)}</text>')

    # baseline
    y0 = y_of(0)
    parts.append(f'<line x1="{ml}" y1="{y0:.1f}" x2="{W-mr}" y2="{y0:.1f}" class="axis"/>')

    for i, h in enumerate(hist):
        cx = ml + slot * i + slot / 2
        bh = plot_h * (h["count"] / max_count)
        x = cx - bar_w / 2
        y = y0 - bh
        is_last = i == n - 1
        lbl = bin_label(h["lo"], h["hi"], is_last)
        cnt = h["count"]
        pct = 100 * cnt / s["n_rows"] if s["n_rows"] else 0
        tip = f'{lbl} tokens · {fmt(cnt)} rows ({pct:.1f}%)'
        # rounded top cap, square base: draw rect with top radius only
        r = 4 if bh > 4 else 0
        parts.append(
            f'<g class="col" tabindex="0">'
            f'<path d="M{x:.1f},{y0:.1f} L{x:.1f},{y+r:.1f} '
            f'Q{x:.1f},{y:.1f} {x+r:.1f},{y:.1f} L{x+bar_w-r:.1f},{y:.1f} '
            f'Q{x+bar_w:.1f},{y:.1f} {x+bar_w:.1f},{y+r:.1f} L{x+bar_w:.1f},{y0:.1f} Z" '
            f'class="bar"/>'
            f'<rect x="{ml+slot*i:.1f}" y="{mt}" width="{slot:.1f}" height="{plot_h}" '
            f'class="hit"><title>{html.escape(tip)}</title></rect>'
        )
        # direct label on cap (only if the column is tall enough to read)
        if h["count"] > 0 and bh > 14:
            parts.append(f'<text x="{cx:.1f}" y="{y-6:.1f}" class="caplabel">{fmt(h["count"])}</text>')
        # x label
        parts.append(
            f'<text x="{cx:.1f}" y="{y0+18:.1f}" class="xtick" '
            f'transform="rotate(35 {cx:.1f} {y0+18:.1f})">{html.escape(lbl)}</text>'
        )
    parts.append(f'<text x="{ml}" y="{H-6}" class="axis-title">token count per row (binned)</text>')
    parts.append("</svg>")
    return "".join(parts)


def percentile_table(a, b):
    keys = ["p1", "p5", "p10", "p25", "p50", "p75", "p90", "p95", "p99"]
    rows = []
    rows.append("<tr><th>Percentile</th><th>raw_markdown</th><th>ocr_markdown</th></tr>")
    for k in keys:
        rows.append(
            f"<tr><td>{k}</td><td>{fmt(a['percentiles'][k])}</td>"
            f"<td>{fmt(b['percentiles'][k])}</td></tr>"
        )
    extra = [
        ("mean", fmt(a["mean"]), fmt(b["mean"])),
        ("std dev", fmt(a["std"]), fmt(b["std"])),
        ("min", fmt(a["min"]), fmt(b["min"])),
        ("max", fmt(a["max"]), fmt(b["max"])),
        ("CV (std/mean)", f"{a['cv']:.2f}", f"{b['cv']:.2f}"),
    ]
    for label, av, bv in extra:
        rows.append(f'<tr class="summ"><td>{label}</td><td>{av}</td><td>{bv}</td></tr>')
    return '<table class="ptable">' + "".join(rows) + "</table>"


def section(title, subtitle, s, chart_id):
    return f"""
    <section class="panel">
      <h2>{html.escape(title)}</h2>
      <p class="sub">{html.escape(subtitle)}</p>
      {stat_tiles(s)}
      <div class="chart-wrap">
        <div class="chart-title">Distribution of LLM tokens per row</div>
        {histogram_svg(s, chart_id)}
      </div>
    </section>
    """


def build(data):
    a = data["raw_markdown"]
    b = data["ocr_markdown"]
    tok = html.escape(data["tokenizer"])
    note = html.escape(data["note"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LLM Token-Size R&amp;D — GovBD Crawl Corpus</title>
<style>
  :root {{
    --plane:#f9f9f7; --surface-1:#fcfcfb;
    --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
    --series:#256abf; --series-soft:#cde2fb;
  }}
  :root[data-theme="dark"] {{
    --plane:#0d0d0d; --surface-1:#1a1a19;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --series:#3987e5; --series-soft:#184f95;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --plane:#0d0d0d; --surface-1:#1a1a19;
      --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
      --series:#3987e5; --series-soft:#184f95;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--plane); color:var(--text-primary);
    font-family: system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.45;
  }}
  .wrap {{ max-width:960px; margin:0 auto; padding:32px 20px 64px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }}
  h1 {{ font-size:26px; margin:0 0 4px; letter-spacing:-0.01em; }}
  .lede {{ color:var(--text-secondary); max-width:640px; margin:0; font-size:14px; }}
  .tokline {{ color:var(--muted); font-size:12.5px; margin-top:8px; }}
  .toggle {{
    border:1px solid var(--border); background:var(--surface-1); color:var(--text-secondary);
    border-radius:8px; padding:7px 12px; font:inherit; font-size:13px; cursor:pointer; white-space:nowrap;
  }}
  .panel {{
    background:var(--surface-1); border:1px solid var(--border); border-radius:14px;
    padding:22px 22px 12px; margin-top:24px;
  }}
  h2 {{ font-size:18px; margin:0 0 2px; }}
  .sub {{ color:var(--text-secondary); font-size:13px; margin:0 0 18px; }}
  .kpi-row {{
    display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:20px;
  }}
  @media (min-width:720px) {{ .kpi-row {{ grid-template-columns:repeat(6,1fr); }} }}
  .tile {{
    border:1px solid var(--border); border-radius:10px; padding:12px 12px 11px; background:var(--plane);
  }}
  .tile-label {{ color:var(--text-secondary); font-size:11.5px; }}
  .tile-value {{ font-size:22px; font-weight:600; letter-spacing:-0.01em; margin:2px 0 1px; }}
  .tile-sub {{ color:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }}
  .chart-title {{ font-size:13px; color:var(--text-secondary); margin:4px 2px 6px; }}
  .chart {{ width:100%; height:auto; display:block; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .axis {{ stroke:var(--axis); stroke-width:1; }}
  .bar {{ fill:var(--series); }}
  .hit {{ fill:transparent; }}
  .col:hover .bar, .col:focus .bar {{ fill:var(--text-primary); opacity:0.85; }}
  .col {{ outline:none; }}
  .ytick {{ fill:var(--muted); font-size:11px; text-anchor:end; font-variant-numeric:tabular-nums; }}
  .xtick {{ fill:var(--muted); font-size:10.5px; text-anchor:start; }}
  .caplabel {{ fill:var(--text-secondary); font-size:10.5px; text-anchor:middle; font-variant-numeric:tabular-nums; }}
  .axis-title {{ fill:var(--muted); font-size:11px; }}
  .grid2 {{ display:grid; gap:18px; grid-template-columns:1fr; }}
  @media (min-width:720px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
  .ptable {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:6px; }}
  .ptable th, .ptable td {{ text-align:right; padding:7px 10px; border-bottom:1px solid var(--border); font-variant-numeric:tabular-nums; }}
  .ptable th:first-child, .ptable td:first-child {{ text-align:left; font-variant-numeric:normal; }}
  .ptable th {{ color:var(--text-secondary); font-weight:600; }}
  .ptable tr.summ td {{ color:var(--text-secondary); }}
  .foot {{ color:var(--muted); font-size:12px; margin-top:28px; }}
  .swatch {{ display:inline-block; width:10px; height:10px; border-radius:2px; background:var(--series); margin-right:6px; vertical-align:middle; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>LLM Token-Size R&amp;D — GovBD Crawl Corpus</h1>
      <p class="lede">Per-row token-size distribution of crawled content, split into
      the page's own markdown and the OCR text pulled from its attached PDFs.</p>
      <p class="tokline"><span class="swatch"></span>Tokenizer: <b>{tok}</b> · {note}</p>
    </div>
    <button class="toggle" onclick="tog()">Toggle theme</button>
  </header>

  {section("A · raw_markdown", "crawled_data.raw_markdown — HTML-derived page content (OCR text migrated out).", a, "chartA")}
  {section("B · ocr_markdown", "crawled_data_ocr.ocr_markdown — text OCR'd from a page's attached PDFs.", b, "chartB")}

  <section class="panel">
    <h2>Distribution detail</h2>
    <p class="sub">Percentiles and dispersion for both fields, in LLM tokens.</p>
    {percentile_table(a, b)}
  </section>

  <p class="foot">Counts computed with the deployed model's own tokenizer (verified equal
  to the live vLLM <code>/tokenize</code> endpoint). These are LLM tokens, not embedding tokens.</p>
</div>
<script>
  function tog() {{
    var r = document.documentElement;
    var cur = r.getAttribute('data-theme');
    var next = cur === 'dark' ? 'light' : (cur === 'light' ? 'dark' :
      (matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark'));
    r.setAttribute('data-theme', next);
  }}
</script>
</body>
</html>
"""


def main():
    with open(IN_JSON, encoding="utf-8") as f:
        data = json.load(f)
    out = build(data)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[+] Wrote {OUT_HTML}")


if __name__ == "__main__":
    main()
