"""
Generate the rebalance order list — which stocks to buy and sell.

Running this script daily is free. TRADING daily is not, and that distinction
is the whole point of the --rebalance / --rank-buffer flags.

Measured on 205 Nifty 200 names, 2011-2026 daily bars, after delivery costs:

    schedule                    turnover/yr   cost/yr    CAGR
    monthly (baseline)              516%       0.94%    29.22%
    monthly + rank buffer 10        323%       0.58%    28.43%
    quarterly                       280%       0.51%    27.77%
    weekly  + rank buffer 10        492%       0.89%    29.72%   <- best
    daily   + rank buffer 20        497%       0.90%    29.54%
    daily   + rank buffer 10        686%       1.24%    28.99%
    weekly, no buffer             1,131%       2.06%    28.50%
    daily,  no buffer             2,624%       4.85%    24.39%   <- worst

Naive daily rebalancing churns names oscillating across the top-N boundary,
costing 4.85%/yr and giving up ~4.8%/yr of CAGR. A rank buffer fixes that:
hold a name until it drops out of the top (n + buffer). With a buffer, a daily
schedule costs no more than a monthly one AND exits faster — daily + buffer 20
turns over less than the monthly baseline. So a daily buy list is not a
compromise; it just requires the buffer.

The workflow
------------
  After the 15:30 close    -> run this script
                           -> on a rebalance day it prints/writes SELL and BUY
                              lists; otherwise it says there is nothing to do
  Next morning at the open -> place those orders as CNC/delivery

Critically, this imports `select()` from strategies/momentum_xs.py — the SAME
function the backtest calls. There is no separate "live" implementation to
drift out of sync with the tested one, which is the single most common way a
backtested strategy stops resembling what actually gets traded.

Usage
-----
    # is today a rebalance day, and what would the orders be?
    python live/generate_orders.py

    # check the list every day, with turnover control
    python live/generate_orders.py --rebalance D --rank-buffer 10

    # ignore the calendar and generate anyway (e.g. initial portfolio build)
    python live/generate_orders.py --force

Positions file (live/positions.json), created on first run:
    {"as_of": "2026-08-31", "capital": 1000000,
     "holdings": {"TCS": 42, "INFY": 63}}

Holdings are share counts. `capital` is only used to size the FIRST build; once
holdings exist, sizing is driven by their current market value plus cash.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import load_daily, rebalance_dates
from backtest.costs import delivery_one_way_cost
from strategies.momentum_xs import MomentumConfig, select

LIVE_DIR = Path(__file__).parent
POSITIONS_FILE = LIVE_DIR / "positions.json"


def load_positions(capital_default):
    if POSITIONS_FILE.exists():
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    return {"as_of": None, "capital": capital_default, "holdings": {}}


def save_positions(pos):
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS_FILE.write_text(json.dumps(pos, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="Generate even if today is not a rebalance date")
    ap.add_argument("--capital", type=float, default=1_000_000.0,
                    help="Only used for the very first portfolio build")
    ap.add_argument("--rebalance", default="ME", choices=["D", "W", "ME", "QE"],
                    help="D=daily, W=weekly, ME=month-end (default), QE=quarter-end. "
                         "Running the SCRIPT daily is free; TRADING daily is not — "
                         "naive daily rebalancing measured 2624%% annual turnover and "
                         "4.85%%/yr in costs. Pair D or W with --rank-buffer.")
    ap.add_argument("--rank-buffer", type=int, default=0,
                    help="Keep holding a name until it drops out of the top "
                         "(n + buffer). Essential for daily/weekly schedules: it cut "
                         "turnover from 2624%% to 497%% and recovered ~5%%/yr "
                         "of CAGR on real data.")
    ap.add_argument("--cash", type=float, default=None,
                    help="Idle cash to deploy alongside current holdings")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the orders but do NOT write positions.json. Use "
                         "this to look at the list without the script recording "
                         "an intended book you have not actually bought.")
    args = ap.parse_args()

    try:
        closes, volumes = load_daily()
    except FileNotFoundError as exc:
        print("No daily data yet.")
        print()
        print(exc)
        return
    asof = closes.index[-1]
    latest_px = closes.loc[asof]

    print("=" * 74)
    print("  REBALANCE — ORDER GENERATION")
    print("=" * 74)
    print(f"  Data through : {asof.date()}")
    print(f"  Universe     : {closes.shape[1]} symbols")

    staleness = (pd.Timestamp(datetime.now().date()) - asof).days
    if staleness > 5:
        print(f"  [WARN] Data is {staleness} days old. Re-run the fetcher before")
        print(f"         trading on this — see RUN_AT_HOME.md.")

    # --- is this actually a rebalance date? --------------------------------
    rebals = rebalance_dates(closes.index, args.rebalance)
    is_rebal = asof in set(rebals)
    sched = {"D": "every trading day", "W": "weekly",
             "ME": "month-end", "QE": "quarter-end"}[args.rebalance]
    print(f"  Rebalance day: {'YES' if is_rebal else 'no'}  (schedule = {sched})")
    if args.rebalance in ("D", "W") and args.rank_buffer == 0:
        print(f"  [WARN] {sched} rebalancing with no rank buffer produced 2161% annual")
        print(f"         turnover and 9.5%/yr of costs in testing. Add --rank-buffer 10.")

    if not is_rebal and not args.force:
        nxt = [d for d in rebals if d > asof]
        print()
        print("  Nothing to do today. This is expected — on a month-end schedule")
        print("  the strategy trades roughly 12 times a year, not daily.")
        print("  To check the list every day instead, use:")
        print("      python live/generate_orders.py --rebalance D --rank-buffer 10")
        if nxt:
            print(f"  Next scheduled rebalance in this data: {nxt[0].date()}")
        else:
            print("  The next rebalance is the last trading day of this month.")
        print("\n  Use --force to generate anyway (e.g. initial portfolio build).")
        return

    # --- what should we hold? ----------------------------------------------
    cfg = MomentumConfig(exit_rank_buffer=args.rank_buffer)
    pos = load_positions(args.capital)
    held = list(pos["holdings"])

    target = select(closes, volumes, asof, cfg, currently_held=held)
    if not target:
        print("\n  No names qualify — everything fails the trend filter.")
        print("  That is a legitimate signal: stay in cash.")
        return

    # --- value the book ----------------------------------------------------
    holdings_value = sum(qty * latest_px.get(s, np.nan)
                         for s, qty in pos["holdings"].items()
                         if np.isfinite(latest_px.get(s, np.nan)))
    cash = args.cash if args.cash is not None else (
        pos["capital"] if not pos["holdings"] else 0.0)
    total_value = holdings_value + cash
    per_name = total_value / len(target)

    print(f"\n  Holdings value: Rs.{holdings_value:,.0f}")
    print(f"  Cash          : Rs.{cash:,.0f}")
    print(f"  Total         : Rs.{total_value:,.0f}")
    print(f"  Target book   : {len(target)} names @ ~Rs.{per_name:,.0f} each")

    sells, buys = [], []

    for sym, qty in pos["holdings"].items():
        if sym not in target:
            p = latest_px.get(sym, np.nan)
            sells.append({"symbol": sym, "action": "SELL", "qty": int(qty),
                          "ref_price": round(float(p), 2) if np.isfinite(p) else None,
                          "value": round(qty * p, 0) if np.isfinite(p) else None,
                          "reason": "dropped out of top rank or below 200-DMA"})

    for sym in target:
        p = latest_px.get(sym, np.nan)
        if not np.isfinite(p) or p <= 0:
            continue
        have = pos["holdings"].get(sym, 0)
        want = int(per_name // p)
        delta = want - have
        if delta > 0 and delta * p > per_name * 0.05:
            buys.append({"symbol": sym, "action": "BUY", "qty": int(delta),
                         "ref_price": round(float(p), 2),
                         "value": round(delta * p, 0),
                         "reason": "new entry" if have == 0 else "top up to weight"})
        elif delta < 0 and abs(delta) * p > per_name * 0.25:
            sells.append({"symbol": sym, "action": "SELL", "qty": int(-delta),
                          "ref_price": round(float(p), 2),
                          "value": round(-delta * p, 0),
                          "reason": "trim to equal weight"})

    orders = pd.DataFrame(sells + buys)

    print("\n" + "=" * 74)
    if orders.empty:
        print("  No orders — the target book already matches current holdings.")
        print("=" * 74)
        return

    print("  ORDERS FOR THE NEXT MARKET OPEN")
    print("=" * 74)
    pd.set_option("display.width", 200)
    print(orders.to_string(index=False))

    est_cost = sum(delivery_one_way_cost(r["value"], r["action"].lower())
                   for _, r in orders.iterrows() if r["value"])
    turnover = orders["value"].sum()
    print(f"\n  Orders        : {len(sells)} sells, {len(buys)} buys")
    print(f"  Traded value  : Rs.{turnover:,.0f}  "
          f"({turnover / total_value * 100:.1f}% turnover)")
    print(f"  Est. cost     : Rs.{est_cost:,.0f}  "
          f"({est_cost / total_value * 1e4:.1f} bps of portfolio)")

    out = LIVE_DIR / f"orders_{asof.date()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    orders.to_csv(out, index=False)
    print(f"\n  Saved: {out}")

    print("\n  Next steps:")
    print("    1. Place these as CNC/delivery orders at the next open.")
    print("    2. ref_price is the rebalance close, not a limit — expect to fill")
    print("       away from it. That difference IS the slippage the backtest")
    print("       assumes at 5 bps/leg; record fills and check the assumption.")
    print(f"    3. Record actual fills, then update {POSITIONS_FILE.name}.")

    # Persist the intended book so the next run has a baseline to diff against.
    #
    # Guarded by --dry-run because simply LOOKING at the list used to record a
    # portfolio you had not bought: the next run would then diff against
    # phantom holdings and emit sells for stock you never owned.
    if args.dry_run:
        print(f"\n    (--dry-run: {POSITIONS_FILE.name} left untouched)")
        return

    projected = dict(pos["holdings"])
    for _, r in orders.iterrows():
        d = int(r["qty"]) * (1 if r["action"] == "BUY" else -1)
        projected[r["symbol"]] = projected.get(r["symbol"], 0) + d
    projected = {k: v for k, v in projected.items() if v > 0}
    save_positions({"as_of": str(asof.date()), "capital": pos["capital"],
                    "holdings": projected,
                    "_note": "INTENDED book from generate_orders. Replace with "
                             "ACTUAL filled quantities before the next rebalance."})
    print(f"    (wrote intended holdings to {POSITIONS_FILE.name} — correct it "
          f"with real fills)")


if __name__ == "__main__":
    main()
