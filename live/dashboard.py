"""
Render the paper portfolio as a self-contained HTML page.

Writes `live/dashboard.html` — one file, no server, no CDN, no network. Open it
in a browser or double-click it. Nothing leaves the machine, which matters
because `positions.json` and `paper_ledger.csv` are gitignored on purpose: this
is a public repo and they describe a real intended book.

The NAV curve is reconstructed by replaying the ledger chronologically and
marking the resulting holdings to the daily closes, so it is derived from
recorded fills rather than stored separately and allowed to drift out of sync.

The benchmark line is equal-weight buy-and-hold over the same window, because
a rising NAV on its own says nothing — the market rises. That comparison is the
one Phase 1b's whole case rests on, so it is drawn on the same axes rather than
quoted in a corner.

Usage:
    python live/dashboard.py
    python live/dashboard.py --open        # also open it in the browser
"""

import argparse
import html
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import load_daily
from live.portfolio_state import LEDGER_FILE, load_positions

OUT_FILE = Path(__file__).parent / "dashboard.html"
ASSUMED_SLIPPAGE_BPS = 5.0


# ----------------------------------------------------------------- data
def rebuild_nav(ledger: pd.DataFrame, closes: pd.DataFrame, capital: float):
    """
    Daily NAV from inception, replayed from the ledger.

    Returns (DataFrame[date, nav, benchmark], inception) or (None, None).
    """
    if ledger.empty or "fill_date" not in ledger.columns:
        return None, None

    led = ledger.copy()
    led["fill_date"] = pd.to_datetime(led["fill_date"], errors="coerce")
    led = led.dropna(subset=["fill_date"]).sort_values("fill_date")
    if led.empty:
        return None, None

    inception = led["fill_date"].min()
    idx = closes.index[closes.index >= inception]
    if len(idx) == 0:
        # Fills are more recent than the price file; show the single point we
        # can defend rather than inventing a curve.
        idx = closes.index[-1:]

    holdings, cash = {}, capital
    rows = []
    by_date = {d: g for d, g in led.groupby("fill_date")}

    for d in idx:
        # apply every fill dated on or before d, exactly once
        due = [fd for fd in list(by_date) if fd <= d]
        for fd in due:
            for _, t in by_date.pop(fd).iterrows():
                q, px, cost = int(t["qty"]), float(t["fill_price"]), float(t["cost_inr"])
                if str(t["action"]).upper() == "BUY":
                    holdings[t["symbol"]] = holdings.get(t["symbol"], 0) + q
                    cash -= q * px + cost
                else:
                    holdings[t["symbol"]] = holdings.get(t["symbol"], 0) - q
                    if holdings[t["symbol"]] <= 0:
                        holdings.pop(t["symbol"], None)
                    cash += q * px - cost

        px_row = closes.loc[d]
        mv = sum(q * px_row.get(s, np.nan) for s, q in holdings.items()
                 if np.isfinite(px_row.get(s, np.nan)))
        rows.append({"date": d, "nav": cash + mv})

    nav = pd.DataFrame(rows).set_index("date")

    # equal-weight buy-and-hold on the same window
    prior = closes.index[closes.index <= inception]
    d0 = prior[-1] if len(prior) else closes.index[0]
    p0 = closes.loc[d0]
    ok = p0.notna() & (p0 > 0)
    bench = (closes.loc[nav.index, ok.index[ok]] / p0[ok]).mean(axis=1) * capital
    nav["benchmark"] = bench
    return nav, inception


def holdings_table(pos, closes, ledger):
    holdings = pos.get("holdings", {})
    if not holdings:
        return pd.DataFrame(), 0.0
    latest = closes.iloc[-1]
    entry = {}
    if not ledger.empty:
        buys = ledger[ledger["action"] == "BUY"]
        for s in holdings:
            b = buys[buys["symbol"] == s]
            q = b["qty"].sum()
            if q > 0:
                entry[s] = float((b["qty"] * b["fill_price"]).sum() / q)
    rows, total = [], 0.0
    for s, q in holdings.items():
        px = latest.get(s, np.nan)
        val = q * px if np.isfinite(px) else 0.0
        total += val
        avg = entry.get(s, np.nan)
        rows.append({
            "sym": s, "qty": q, "entry": avg, "px": px, "val": val,
            "pnl": (px - avg) * q if np.isfinite(px) and np.isfinite(avg) else np.nan,
            "ret": (px / avg - 1) * 100 if np.isfinite(px) and np.isfinite(avg) and avg > 0 else np.nan,
        })
    return pd.DataFrame(rows).sort_values("val", ascending=False), total


# ----------------------------------------------------------------- render
def svg_chart(nav: pd.DataFrame, w=900, h=280, pad=44) -> str:
    """Inline SVG line chart — NAV against the buy-and-hold benchmark."""
    if nav is None or len(nav) < 2:
        return ('<p class="muted">The NAV curve needs at least two trading days '
                'of fills. It will appear after the next rebalance.</p>')

    xs = np.arange(len(nav))
    lo = float(min(nav["nav"].min(), nav["benchmark"].min()))
    hi = float(max(nav["nav"].max(), nav["benchmark"].max()))
    span = (hi - lo) or max(hi * 0.01, 1.0)
    lo, hi = lo - span * 0.08, hi + span * 0.08

    def pt(i, v):
        x = pad + (w - 2 * pad) * (i / max(len(nav) - 1, 1))
        y = h - pad - (h - 2 * pad) * ((v - lo) / (hi - lo))
        return f"{x:.1f},{y:.1f}"

    line_s = " ".join(pt(i, v) for i, v in enumerate(nav["nav"]))
    line_b = " ".join(pt(i, v) for i, v in enumerate(nav["benchmark"]))

    grid, labels = [], []
    for f in (0, 0.25, 0.5, 0.75, 1.0):
        y = h - pad - (h - 2 * pad) * f
        grid.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w-pad}" y2="{y:.1f}" '
                    f'class="grid"/>')
        labels.append(f'<text x="{pad-8}" y="{y+4:.1f}" class="ytick">'
                      f'{(lo + (hi-lo)*f)/1000:,.0f}k</text>')
    for i in (0, len(nav) - 1):
        x = pad + (w - 2 * pad) * (i / max(len(nav) - 1, 1))
        labels.append(f'<text x="{x:.1f}" y="{h-pad+18}" class="xtick" '
                      f'text-anchor="{"start" if i == 0 else "end"}">'
                      f'{nav.index[i].date()}</text>')

    return f"""<div class="chartwrap"><svg viewBox="0 0 {w} {h}" class="chart"
  role="img" aria-label="Paper NAV against equal-weight buy and hold">
  {''.join(grid)}
  <polyline points="{line_b}" class="lb"/>
  <polyline points="{line_s}" class="ls"/>
  {''.join(labels)}
</svg></div>
<p class="legend"><span class="sw ss"></span>Momentum book
   <span class="sw sb"></span>Equal-weight buy &amp; hold</p>"""


def kpi(label, value, sub="", tone=""):
    return (f'<div class="kpi {tone}"><div class="kl">{html.escape(label)}</div>'
            f'<div class="kv">{value}</div>'
            f'<div class="ks">{sub}</div></div>')


def build_html(pos, closes, ledger) -> str:
    capital = float(pos.get("capital", 1_000_000.0))
    cash = float(pos.get("cash", 0.0))
    tbl, mv = holdings_table(pos, closes, ledger)
    nav_val = cash + mv
    pnl = nav_val - capital
    nav, inception = rebuild_nav(ledger, closes, capital)

    bench_val, edge, days = None, None, None
    if nav is not None and len(nav):
        bench_val = float(nav["benchmark"].iloc[-1])
        edge = (nav_val / capital - bench_val / capital) * 100
        days = (nav.index[-1] - nav.index[0]).days

    stale = (pd.Timestamp(datetime.now().date()) - closes.index[-1]).days
    # Any source other than a real quote is simulated. Checking only for
    # "mock" would let a replayed or hand-edited ledger read as live.
    sim_n = int((ledger.get("source", pd.Series(dtype=str))
                 != "smartapi_live").sum()) if not ledger.empty else 0

    banners = []
    if sim_n:
        banners.append(
            f'<div class="banner warn"><b>{sim_n} of {len(ledger)} fills are '
            f'simulated, not live quotes.</b> Synthetic slippage is recovered '
            f'exactly as injected, so every execution number below describes '
            f'the simulation rather than the market. Delete '
            f'<code>live/paper_ledger.csv</code> before the first real run.</div>')
    if stale > 5:
        banners.append(
            f'<div class="banner warn"><b>Prices are {stale} days old.</b> '
            f'Refresh with the daily fetch before reading these marks — see '
            f'<code>RUN_AT_HOME.md</code>.</div>')
    if days is not None and days < 365:
        banners.append(
            f'<div class="banner info"><b>{days} days of history.</b> The '
            f'backtested edge is about 1%/month against monthly swings of '
            f'several percent. A window this short cannot separate skill from '
            f'noise — treat it as a wiring check.</div>')

    kpis = "".join([
        kpi("NAV", f"₹{nav_val:,.0f}", f"from ₹{capital:,.0f} capital"),
        kpi("P&amp;L", f"{pnl:+,.0f}", f"{pnl/capital*100:+.2f}%",
            "pos" if pnl >= 0 else "neg"),
        kpi("Buy &amp; hold", f"₹{bench_val:,.0f}" if bench_val else "—",
            "same window, equal weight"),
        kpi("Edge", f"{edge:+.2f}%" if edge is not None else "—",
            "vs benchmark" + (f", {days}d" if days else ""),
            ("pos" if edge >= 0 else "neg") if edge is not None else ""),
        kpi("Holdings", f"{len(pos.get('holdings', {}))}",
            f"₹{mv:,.0f} invested"),
        kpi("Cash", f"₹{cash:,.0f}",
            f"{cash/nav_val*100:.1f}% of NAV" if nav_val else ""),
    ])

    rows = ""
    for _, r in tbl.iterrows():
        cls = "pos" if (np.isfinite(r["ret"]) and r["ret"] >= 0) else "neg"
        rows += (f'<tr><td class="sym">{html.escape(str(r["sym"]))}</td>'
                 f'<td>{int(r["qty"]):,}</td>'
                 f'<td>{r["entry"]:,.2f}</td><td>{r["px"]:,.2f}</td>'
                 f'<td>{r["val"]:,.0f}</td>'
                 f'<td class="{cls}">{r["pnl"]:+,.0f}</td>'
                 f'<td class="{cls}">{r["ret"]:+.2f}%</td></tr>')
    holdings_html = (f'<table><thead><tr><th>Symbol</th><th>Qty</th>'
                     f'<th>Entry</th><th>Price</th><th>Value</th>'
                     f'<th>P&amp;L</th><th>Return</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table>') if rows else \
        '<p class="muted">No open positions.</p>'

    exec_html = '<p class="muted">No fills recorded yet.</p>'
    if not ledger.empty:
        slip = pd.to_numeric(ledger["slippage_bps"], errors="coerce").dropna()
        traded = float(ledger["traded_value"].sum())
        costs = float(ledger["cost_inr"].sum())
        n = len(slip)
        se = slip.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
        ci = (f"{slip.mean()-2*se:+.1f} … {slip.mean()+2*se:+.1f} bps"
              if np.isfinite(se) else "—")
        verdict = ("not yet resolvable — the interval spans the assumption"
                   if np.isfinite(se) and
                   slip.mean() - 2*se <= ASSUMED_SLIPPAGE_BPS <= slip.mean() + 2*se
                   else "outside the assumed 5 bps — check fill timing first")
        exec_html = f"""<div class="grid2">
  <div><div class="kl">Fills</div><div class="kv2">{len(ledger)}</div></div>
  <div><div class="kl">Traded value</div><div class="kv2">₹{traded:,.0f}</div></div>
  <div><div class="kl">Costs paid</div><div class="kv2">₹{costs:,.0f}
       <span class="muted">({costs/traded*1e4:.1f} bps)</span></div></div>
  <div><div class="kl">Mean slippage</div><div class="kv2">{slip.mean():+.2f} bps
       <span class="muted">(assumed 5.0)</span></div></div>
  <div><div class="kl">95% interval</div><div class="kv2">{ci}</div></div>
  <div><div class="kl">Reading</div><div class="kv2 small">{verdict}</div></div>
</div>
<p class="note">Per-leg noise is about 112 bps, so roughly 3,100 legs are needed
to pin the mean within ±2 bps — around 13 years of monthly rebalances. Paper
trading will not settle the slippage question;
<code>backtest/test_execution_gap.py</code> already measured it at +0.8 bps net
across 1,740 historical legs, which makes the 5 bps assumption conservative.</p>"""

    return f"""<title>Momentum Paper Book</title>
<style>
:root {{
  --bg:#fbfbfa; --panel:#fff; --ink:#1d1c1a; --muted:#6b6862; --line:#e6e3dd;
  --pos:#1a7f4b; --neg:#b3261e; --accent:#3b5bdb; --bench:#a8a29a;
  --warn-bg:#fdf6e3; --warn-line:#e0c56e; --info-bg:#eef2fb; --info-line:#c3cef0;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#17171a; --panel:#1f1f23; --ink:#eceae6; --muted:#9a958c; --line:#33323a;
    --pos:#4ec98a; --neg:#f2827a; --accent:#8aa4ff; --bench:#6f6b64;
    --warn-bg:#2b2418; --warn-line:#7a6428; --info-bg:#1c2233; --info-line:#39456e;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#17171a; --panel:#1f1f23; --ink:#eceae6; --muted:#9a958c; --line:#33323a;
  --pos:#4ec98a; --neg:#f2827a; --accent:#8aa4ff; --bench:#6f6b64;
  --warn-bg:#2b2418; --warn-line:#7a6428; --info-bg:#1c2233; --info-line:#39456e;
}}
* {{ box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--ink); margin:0; padding:28px 20px 60px;
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:980px; margin:0 auto; }}
h1 {{ font-size:22px; margin:0 0 2px; letter-spacing:-.01em; }}
h2 {{ font-size:15px; margin:32px 0 12px; text-transform:uppercase;
  letter-spacing:.07em; color:var(--muted); font-weight:600; }}
.sub {{ color:var(--muted); font-size:13px; margin:0 0 20px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
  gap:10px; }}
.kpi {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:13px 15px; }}
.kl {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); }}
.kv {{ font-size:21px; font-weight:600; margin-top:3px;
  font-variant-numeric:tabular-nums; letter-spacing:-.02em; }}
.kv2 {{ font-size:16px; font-weight:600; margin-top:2px;
  font-variant-numeric:tabular-nums; }}
.kv2.small {{ font-size:13px; font-weight:500; color:var(--muted); }}
.ks {{ font-size:11.5px; color:var(--muted); margin-top:2px; }}
.kpi.pos .kv {{ color:var(--pos); }} .kpi.neg .kv {{ color:var(--neg); }}
.banner {{ border-radius:9px; padding:11px 14px; margin:16px 0; font-size:13.5px;
  border:1px solid; }}
.banner.warn {{ background:var(--warn-bg); border-color:var(--warn-line); }}
.banner.info {{ background:var(--info-bg); border-color:var(--info-line); }}
.chartwrap {{ overflow-x:auto; background:var(--panel); border:1px solid var(--line);
  border-radius:10px; padding:8px; }}
.chart {{ width:100%; min-width:560px; height:auto; display:block; }}
.grid {{ stroke:var(--line); stroke-width:1; }}
.ls {{ fill:none; stroke:var(--accent); stroke-width:2.2; stroke-linejoin:round; }}
.lb {{ fill:none; stroke:var(--bench); stroke-width:1.8; stroke-dasharray:5 4; }}
.ytick,.xtick {{ fill:var(--muted); font-size:10.5px; }}
.ytick {{ text-anchor:end; }}
.legend {{ font-size:12.5px; color:var(--muted); margin:9px 0 0; }}
.sw {{ display:inline-block; width:16px; height:3px; border-radius:2px;
  margin:0 6px 0 14px; vertical-align:middle; }}
.legend .sw:first-child {{ margin-left:0; }}
.ss {{ background:var(--accent); }} .sb {{ background:var(--bench); }}
table {{ width:100%; border-collapse:collapse; font-size:13.5px;
  font-variant-numeric:tabular-nums; }}
th,td {{ padding:7px 9px; text-align:right; border-bottom:1px solid var(--line); }}
th {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em;
  color:var(--muted); font-weight:600; }}
th:first-child,td:first-child {{ text-align:left; }}
.sym {{ font-weight:600; }}
td.pos {{ color:var(--pos); }} td.neg {{ color:var(--neg); }}
.grid2 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:14px; background:var(--panel); border:1px solid var(--line);
  border-radius:10px; padding:16px; }}
.muted {{ color:var(--muted); font-weight:400; }}
.note {{ font-size:13px; color:var(--muted); margin-top:14px; }}
code {{ background:var(--bg); border:1px solid var(--line); border-radius:4px;
  padding:1px 5px; font-size:12.5px; }}
footer {{ margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
  font-size:12px; color:var(--muted); }}
</style>

<div class="wrap">
  <h1>Momentum paper book</h1>
  <p class="sub">Cross-sectional 12-1 momentum, top 20 equal-weight, 200-DMA
     filter · simulated fills, no capital at risk · marked to the
     {closes.index[-1].date()} close</p>

  {''.join(banners)}

  <div class="kpis">{kpis}</div>

  <h2>NAV vs buy &amp; hold</h2>
  {svg_chart(nav)}

  <h2>Holdings</h2>
  {holdings_html}

  <h2>Execution audit</h2>
  {exec_html}

  <footer>
    Generated {datetime.now():%Y-%m-%d %H:%M} by <code>live/dashboard.py</code>.
    Regenerate after every rebalance. This file, <code>positions.json</code> and
    <code>paper_ledger.csv</code> are gitignored — the repository is public.
  </footer>
</div>"""


def main():
    ap = argparse.ArgumentParser(description="Render the paper book as HTML")
    ap.add_argument("--open", action="store_true", help="Open in the browser")
    ap.add_argument("--out", default=None, help="Output path")
    args = ap.parse_args()

    pos = load_positions()
    ledger = pd.read_csv(LEDGER_FILE) if LEDGER_FILE.exists() else pd.DataFrame()
    closes, _ = load_daily()

    out = Path(args.out) if args.out else OUT_FILE
    out.write_text(build_html(pos, closes, ledger), encoding="utf-8")
    print(f"Wrote {out}")
    if not pos.get("holdings") and ledger.empty:
        print("  (the book is empty — the page will say so)")
    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
