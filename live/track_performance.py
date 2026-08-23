"""
Mark the paper book to market, against the benchmark that actually matters.

A long-only equity book making money proves nothing — the market rises. The
whole Phase 1b case rests on beating equal-weight buy-and-hold by >=3%/yr after
costs, so that comparison is computed here rather than described. Without it a
green P&L number is not evidence of anything.

Three things this reports, in descending order of how much they should move a
decision:

  1. NAV vs equal-weight buy-and-hold over the SAME elapsed window. This is the
     forward out-of-sample record the compromised 24-month holdout can no
     longer provide, and the only one that accrues honestly from here.
  2. Realised costs against the modelled delivery cost. Cheap to verify and
     should match closely — the cost model is arithmetic, not a forecast.
  3. Realised slippage, reported WITH its standard error. Per-leg noise is
     ~112 bps (see backtest/test_execution_gap.py), so a handful of rebalances
     cannot resolve 5 bps. Printed for completeness, not for judgement.

Usage:
    python live/track_performance.py
    python live/track_performance.py --live      # mark against live quotes
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import load_daily
from live.portfolio_state import POSITIONS_FILE, LEDGER_FILE, load_positions

ASSUMED_SLIPPAGE_BPS = 5.0


def read_ledger() -> pd.DataFrame:
    if not LEDGER_FILE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(LEDGER_FILE)
    except Exception:
        return pd.DataFrame()


def analyse_ledger(df: pd.DataFrame) -> dict:
    """Cumulative traded value, costs, and slippage with its standard error."""
    if df.empty:
        return {}
    slip = pd.to_numeric(df.get("slippage_bps"), errors="coerce").dropna()
    traded = float(df["traded_value"].sum())
    costs = float(df["cost_inr"].sum())
    n = len(slip)
    se = float(slip.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return {
        "n_trades": len(df),
        "n_buys": int((df["action"] == "BUY").sum()),
        "n_sells": int((df["action"] == "SELL").sum()),
        "traded_value": traded,
        "costs_paid": costs,
        "cost_bps": costs / traded * 1e4 if traded else 0.0,
        "slip_mean": float(slip.mean()) if n else 0.0,
        "slip_median": float(slip.median()) if n else 0.0,
        "slip_se": se,
        "slip_min": float(slip.min()) if n else 0.0,
        "slip_max": float(slip.max()) if n else 0.0,
        "slip_n": n,
        "mock_rows": int((df.get("source", pd.Series(dtype=str)) == "mock").sum()),
    }


def live_prices(symbols: list, latest_closes: pd.Series) -> dict:
    """Live LTPs where available, latest daily close otherwise."""
    try:
        from data.fetch_universe import load_credentials, authenticate
        from live.paper_broker import fetch_live_quotes
        quotes = fetch_live_quotes(authenticate(load_credentials()), symbols)
        return {s: quotes.get(s, {}).get("ltp", latest_closes.get(s, np.nan))
                for s in symbols}
    except Exception as e:
        print(f"  [WARN] Live quotes unavailable ({e}). Using latest close.")
        return {s: latest_closes.get(s, np.nan) for s in symbols}


def mark_to_market(pos: dict, closes: pd.DataFrame, ledger: pd.DataFrame,
                   use_live: bool):
    """Per-holding valuation table and total market value."""
    holdings = pos.get("holdings", {})
    if not holdings:
        return pd.DataFrame(), 0.0

    latest = closes.iloc[-1]
    symbols = list(holdings)
    prices = live_prices(symbols, latest) if use_live else \
        {s: latest.get(s, np.nan) for s in symbols}

    entry = {}
    if not ledger.empty:
        buys = ledger[ledger["action"] == "BUY"]
        for s in symbols:
            b = buys[buys["symbol"] == s]
            q = b["qty"].sum()
            if q > 0:
                entry[s] = float((b["qty"] * b["fill_price"]).sum() / q)

    rows, total = [], 0.0
    for s, qty in holdings.items():
        px = prices.get(s, np.nan)
        val = qty * px if np.isfinite(px) else 0.0
        total += val
        avg = entry.get(s, np.nan)
        pnl = (px - avg) * qty if np.isfinite(px) and np.isfinite(avg) else np.nan
        pct = (px / avg - 1) * 100 if np.isfinite(px) and np.isfinite(avg) and avg > 0 else np.nan
        rows.append({"Symbol": s, "Qty": qty, "Entry": avg, "Price": px,
                     "Value": val, "P&L": pnl, "Ret%": pct})
    df = pd.DataFrame(rows).sort_values("Value", ascending=False)
    return df, total


def benchmark_nav(closes: pd.DataFrame, start_date, capital: float):
    """
    Equal-weight buy-and-hold NAV over the same window as the paper book.

    Equal-weight buy-and-hold needs no portfolio engine: with capital split
    evenly at inception, NAV is just capital x mean(price_now / price_start)
    across the names that were tradable on the start date.
    """
    idx = closes.index
    start = pd.Timestamp(start_date)
    prior = idx[idx <= start]
    if len(prior) == 0:
        return None
    d0 = prior[-1]
    p0, p1 = closes.loc[d0], closes.iloc[-1]
    ok = p0.notna() & p1.notna() & (p0 > 0)
    if not ok.any():
        return None
    growth = float((p1[ok] / p0[ok]).mean())
    return {"start": d0, "end": idx[-1], "n_symbols": int(ok.sum()),
            "growth": growth, "nav": capital * growth,
            "return_pct": (growth - 1) * 100}


def main():
    ap = argparse.ArgumentParser(description="Phase 2 paper portfolio tracker")
    ap.add_argument("--live", action="store_true",
                    help="Mark against live SmartAPI quotes instead of last close")
    args = ap.parse_args()

    pos = load_positions()
    ledger = read_ledger()
    closes, _ = load_daily()

    capital = float(pos.get("capital", 1_000_000.0))
    cash = float(pos.get("cash", 0.0))
    table, holdings_val = mark_to_market(pos, closes, ledger, args.live)
    nav = cash + holdings_val
    pnl = nav - capital

    print("=" * 92)
    print("  PAPER PORTFOLIO — DELIVERY MOMENTUM")
    print("=" * 92)

    if ledger.empty and not pos.get("holdings"):
        print("\n  Nothing traded yet. The book is uninvested.\n")
        print(f"    Capital : Rs.{capital:,.2f}")
        print(f"    Cash    : Rs.{cash:,.2f}\n")
        print("  Start it with:")
        print("    python live/generate_orders.py --force --rank-buffer 20")
        print("    python live/paper_broker.py          # the NEXT trading morning")
        print("=" * 92)
        return

    print(f"  As of            : {pos.get('as_of') or 'not set'}")
    print(f"  Priced from      : "
          f"{'live quotes' if args.live else f'daily close {closes.index[-1].date()}'}")
    print(f"  Capital          : Rs.{capital:,.2f}")
    print(f"  Holdings         : Rs.{holdings_val:,.2f}  ({len(pos.get('holdings', {}))} names)")
    print(f"  Cash             : Rs.{cash:,.2f}")
    print(f"  NAV              : Rs.{nav:,.2f}")
    print(f"  P&L              : Rs.{pnl:+,.2f}  ({pnl / capital * 100:+.2f}%)")

    # ---------------------------------------------------- the comparison
    start_date = None
    if not ledger.empty and "fill_date" in ledger.columns:
        fd = pd.to_datetime(ledger["fill_date"], errors="coerce").dropna()
        if len(fd):
            start_date = fd.min()
    if start_date is None:
        start_date = pd.to_datetime(pos.get("as_of"), errors="coerce")

    print("\n" + "=" * 92)
    print("  VS EQUAL-WEIGHT BUY-AND-HOLD  —  the bar Phase 1b was set against")
    print("=" * 92)
    bench = benchmark_nav(closes, start_date, capital) if pd.notna(start_date) else None
    if bench is None:
        print("  Not computable yet — no inception date recorded in the ledger.")
    else:
        days = max((bench["end"] - bench["start"]).days, 1)
        strat_ret = pnl / capital * 100
        edge = strat_ret - bench["return_pct"]
        print(f"  Window           : {bench['start'].date()} -> {bench['end'].date()} "
              f"({days} days, {bench['n_symbols']} symbols)")
        print(f"  Momentum book    : {strat_ret:+.2f}%   (NAV Rs.{nav:,.0f})")
        print(f"  Buy-and-hold     : {bench['return_pct']:+.2f}%   "
              f"(NAV Rs.{bench['nav']:,.0f})")
        print(f"  Edge             : {edge:+.2f}%")
        if days >= 365:
            yrs = days / 365.25
            ann = ((nav / capital) ** (1 / yrs) - 1) * 100
            bann = (bench["growth"] ** (1 / yrs) - 1) * 100
            print(f"  Annualised       : momentum {ann:+.2f}%/yr vs "
                  f"benchmark {bann:+.2f}%/yr  (edge {ann - bann:+.2f}%/yr)")
            print(f"  Criterion 1 bar  : +3.00%/yr  "
                  f"[{'PASS' if ann - bann >= 3 else 'not met'}]")
        else:
            print(f"\n  Too short to annualise ({days} days). Backtested monthly")
            print("  edge is ~1%, against monthly swings of several percent — a")
            print("  window this size cannot separate skill from noise. Read it")
            print("  as a wiring check, not a result.")

    if not table.empty:
        print("\n" + "=" * 92)
        print("  HOLDINGS")
        print("=" * 92)
        pd.set_option("display.width", 200)
        print(table.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

    # ---------------------------------------------------- costs & slippage
    st = analyse_ledger(ledger)
    if st:
        print("\n" + "=" * 92)
        print("  EXECUTION AUDIT")
        print("=" * 92)
        if st["mock_rows"]:
            print(f"  [WARN] {st['mock_rows']} of {st['n_trades']} ledger rows are "
                  f"MOCK fills. Synthetic slippage")
            print(f"         is recovered exactly as injected and measures nothing. "
                  f"Delete {LEDGER_FILE.name}")
            print(f"         before the first real run.")
        print(f"  Trades           : {st['n_trades']} "
              f"({st['n_buys']} buys, {st['n_sells']} sells)")
        print(f"  Traded value     : Rs.{st['traded_value']:,.2f}")
        print(f"  Costs paid       : Rs.{st['costs_paid']:,.2f} "
              f"({st['cost_bps']:.1f} bps)")
        print(f"  Slippage         : mean {st['slip_mean']:+.2f} bps, "
              f"median {st['slip_median']:+.2f}, "
              f"range {st['slip_min']:+.1f}..{st['slip_max']:+.1f}")

        se = st["slip_se"]
        if np.isfinite(se) and se > 0:
            lo, hi = st["slip_mean"] - 2 * se, st["slip_mean"] + 2 * se
            print(f"  95% interval     : {lo:+.1f} .. {hi:+.1f} bps "
                  f"(n={st['slip_n']}, SE {se:.2f})")
            if lo <= ASSUMED_SLIPPAGE_BPS <= hi:
                print(f"  vs {ASSUMED_SLIPPAGE_BPS:.0f} bps assumed : consistent — "
                      f"but the interval is {hi - lo:.1f} bps wide, so this is")
                print(f"                     not yet evidence either way.")
            elif hi < ASSUMED_SLIPPAGE_BPS:
                print(f"  vs {ASSUMED_SLIPPAGE_BPS:.0f} bps assumed : realised is "
                      f"LOWER — the cost model is conservative.")
            else:
                print(f"  vs {ASSUMED_SLIPPAGE_BPS:.0f} bps assumed : realised is "
                      f"HIGHER. Check fill timing and order sizes")
                print(f"                     in the thinnest names before "
                      f"reading anything else.")
        print()
        print("  Per-leg noise is ~112 bps (backtest/test_execution_gap.py), so")
        print("  ~3,100 legs are needed to pin the mean to +/-2 bps. Paper trading")
        print("  will not settle the slippage question; that script already did.")

    print("=" * 92)


if __name__ == "__main__":
    main()
