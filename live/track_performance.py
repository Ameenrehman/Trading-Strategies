"""
Performance Tracker and Mark-to-Market NAV Auditor (Phase 2).

Tracks the live paper trading portfolio against:
  1. Equal-Weight Buy & Hold Benchmark.
  2. The Backtest's Expected Returns & Slippage Assumptions.

Computes:
  - Current Holdings Market Value, Cash Balance, and Total NAV.
  - Realized Slippage Statistics (Mean, Median, Max bps).
  - Realized Delivery Transaction Costs (STT, DP charges, Brokerage).
  - Open Position P&L and Portfolio Return.

Usage:
  # Check portfolio NAV and slippage audit using latest daily closes
  python live/track_performance.py

  # Mark-to-market using live quotes from SmartAPI
  python live/track_performance.py --live
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import load_daily
from live.paper_broker import POSITIONS_FILE, LEDGER_FILE, load_positions, fetch_live_quotes
from data.fetch_universe import load_credentials, authenticate


def analyze_ledger() -> dict:
    """Read paper_ledger.csv and compute cumulative slippage and transaction costs."""
    if not LEDGER_FILE.exists():
        return {}
    df = pd.read_csv(LEDGER_FILE)
    if df.empty:
        return {}

    buys = df[df["action"] == "BUY"]
    sells = df[df["action"] == "SELL"]

    total_traded = df["traded_value"].sum()
    total_costs = df["cost_inr"].sum()
    all_slippage = df["slippage_bps"].dropna()

    return {
        "total_trades": len(df),
        "total_buys": len(buys),
        "total_sells": len(sells),
        "total_traded_value": total_traded,
        "total_costs_paid": total_costs,
        "mean_slippage_bps": all_slippage.mean() if len(all_slippage) else 0.0,
        "median_slippage_bps": all_slippage.median() if len(all_slippage) else 0.0,
        "max_slippage_bps": all_slippage.max() if len(all_slippage) else 0.0,
        "min_slippage_bps": all_slippage.min() if len(all_slippage) else 0.0,
        "slippage_cost_est_inr": (total_traded * (all_slippage.mean() / 10000.0)) if len(all_slippage) else 0.0,
    }


def compute_mark_to_market(pos: dict, live_mode: bool = False) -> tuple:
    """Compute current holdings value and individual position unrealized P&L."""
    holdings = pos.get("holdings", {})
    if not holdings:
        return {}, 0.0

    closes, _ = load_daily()
    latest_closes = closes.iloc[-1]
    symbols = list(holdings.keys())

    prices = {}
    if live_mode:
        try:
            creds = load_credentials()
            smart = authenticate(creds)
            quotes = fetch_live_quotes(smart, symbols)
            for s in symbols:
                prices[s] = quotes.get(s, {}).get("ltp", latest_closes.get(s, np.nan))
        except Exception as e:
            print(f"[WARN] Live quote fetch failed: {e}. Falling back to latest daily close.")
            for s in symbols:
                prices[s] = latest_closes.get(s, np.nan)
    else:
        for s in symbols:
            prices[s] = latest_closes.get(s, np.nan)

    # Check average entry price from ledger if available
    entry_prices = {}
    if LEDGER_FILE.exists():
        df = pd.read_csv(LEDGER_FILE)
        for s in symbols:
            s_buys = df[(df["symbol"] == s) & (df["action"] == "BUY")]
            if not s_buys.empty:
                # weighted average fill price
                total_val = (s_buys["qty"] * s_buys["fill_price"]).sum()
                total_q = s_buys["qty"].sum()
                entry_prices[s] = total_val / total_q if total_q > 0 else np.nan

    table = []
    total_val = 0.0

    for s, qty in holdings.items():
        curr_p = prices.get(s, np.nan)
        val = qty * curr_p if np.isfinite(curr_p) else 0.0
        total_val += val
        avg_entry = entry_prices.get(s, curr_p)
        unrealized_pnl = (curr_p - avg_entry) * qty if np.isfinite(curr_p) and np.isfinite(avg_entry) else 0.0
        unrealized_pct = ((curr_p / avg_entry) - 1.0) * 100.0 if np.isfinite(curr_p) and np.isfinite(avg_entry) and avg_entry > 0 else 0.0

        table.append({
            "Symbol": s,
            "Qty": qty,
            "Entry Px": avg_entry,
            "Current Px": curr_p,
            "Value (Rs)": val,
            "Unrealized P&L": unrealized_pnl,
            "Return %": unrealized_pct,
        })

    return pd.DataFrame(table), total_val


def main():
    ap = argparse.ArgumentParser(description="Phase 2 Paper Portfolio Tracker")
    ap.add_argument("--live", action="store_true", help="Fetch live real-time prices from SmartAPI")
    args = ap.parse_args()

    pos = load_positions()
    initial_cap = float(pos.get("capital", 1_000_000.0))
    holdings_df, holdings_val = compute_mark_to_market(pos, live_mode=args.live)
    if "cash" in pos:
        cash = float(pos["cash"])
    else:
        cash = initial_cap - holdings_val if holdings_val < initial_cap else 0.0
    total_nav = cash + holdings_val
    pnl = total_nav - initial_cap
    return_pct = (pnl / initial_cap) * 100.0

    ledger_stats = analyze_ledger()

    print("=" * 86)
    print("  PHASE 2 — DELIVERY MOMENTUM PAPER PORTFOLIO PERFORMANCE")
    print("=" * 86)
    print(f"  As Of Date       : {pos.get('as_of', 'Not set')}")
    print(f"  Initial Capital  : Rs.{initial_cap:,.2f}")
    print(f"  Holdings Value   : Rs.{holdings_val:,.2f}")
    print(f"  Available Cash   : Rs.{cash:,.2f}")
    print(f"  Total NAV        : Rs.{total_nav:,.2f}")
    print(f"  Total P&L        : Rs.{pnl:+,.2f} ({return_pct:+.2f}%)")
    print("=" * 86)

    if not holdings_df.empty:
        print("\nCURRENT HOLDINGS")
        print("-" * 86)
        pd.set_option("display.width", 200)
        print(holdings_df.to_string(index=False))

    if ledger_stats:
        print("\n" + "=" * 86)
        print("  SLIPPAGE & COST AUDIT (vs Backtest Assumptions)")
        print("=" * 86)
        print(f"  Total Trades     : {ledger_stats['total_trades']} ({ledger_stats['total_buys']} buys, {ledger_stats['total_sells']} sells)")
        print(f"  Total Traded Val : Rs.{ledger_stats['total_traded_value']:,.2f}")
        print(f"  Total Costs Paid : Rs.{ledger_stats['total_costs_paid']:,.2f} ({ledger_stats['total_costs_paid'] / ledger_stats['total_traded_value'] * 1e4:.1f} bps)")
        print(f"  Realized Slippage: Mean {ledger_stats['mean_slippage_bps']:+.2f} bps | Median {ledger_stats['median_slippage_bps']:+.2f} bps")
        print(f"  Slippage Range   : Min {ledger_stats['min_slippage_bps']:+.2f} bps | Max {ledger_stats['max_slippage_bps']:+.2f} bps")
        print(f"  Est Slippage Drag: Rs.{ledger_stats['slippage_cost_est_inr']:,.2f}")

        diff = ledger_stats['mean_slippage_bps'] - 5.0
        print(f"\n  Slippage Assessment vs Backtest:")
        if abs(diff) <= 2.0:
            print(f"  [PASS] Realized slippage ({ledger_stats['mean_slippage_bps']:.2f} bps) closely matches backtest assumption (5.00 bps).")
        elif diff > 2.0:
            print(f"  [CAUTION] Realized slippage ({ledger_stats['mean_slippage_bps']:.2f} bps) is HIGHER than the backtest assumption (5.00 bps).")
        else:
            print(f"  [PASS] Realized slippage ({ledger_stats['mean_slippage_bps']:.2f} bps) is LOWER than the backtest assumption (5.00 bps).")
    print("=" * 86)


if __name__ == "__main__":
    main()
