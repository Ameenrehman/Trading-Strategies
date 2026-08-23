"""
Local paper broker — simulate fills against real quotes, with no money at risk.

What Phase 2 is actually for
----------------------------
The original intent was to measure slippage. `backtest/test_execution_gap.py`
now shows that cannot work: the close-to-open gap has a standard deviation of
~112 bps per leg, so a year of paper trading (~240 legs) pins the mean only to
+/-7 bps — it cannot tell 5 bps from 0 bps from 15 bps. The 1,700-leg historical
estimate in that script is the better measurement, and it says the 5 bps/leg
assumption is conservative.

So this exists for what it CAN establish:

  1. The pipeline runs end to end — fetch, rank, order, fill, mark to market.
  2. A forward out-of-sample track record. The 24-month holdout was observed
     during the first real-data run, so forward time is the only clean
     out-of-sample left.
  3. Market impact — the gap between the printed open and YOUR fill. That is
     the one execution cost history cannot show, and it needs real orders.

Fill timing is not optional
---------------------------
The signal is computed from the close of day T. The fill must be at an open
AFTER day T. Filling at day T's own open means buying at a price set six hours
before the signal that chose the name — a look-ahead that quietly reports
favourable slippage. On the current order list it measured -5.3 bps, which
reads as free money. This module refuses to do it.

Usage:
    python live/paper_broker.py                      # fill latest orders at today's open
    python live/paper_broker.py --mock               # offline wiring test
    python live/paper_broker.py --orders live/orders_2026-08-21.csv
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

from backtest.costs import delivery_one_way_cost
from data.fetch_universe import load_credentials, authenticate, resolve_tokens

from live.portfolio_state import (POSITIONS_FILE, LEDGER_FILE,
                                  DEFAULT_CAPITAL, load_positions,
                                  save_positions, blank_positions)

LIVE_DIR = Path(__file__).parent


def append_to_ledger(trade_records: list):
    if not trade_records:
        return
    df = pd.DataFrame(trade_records)
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = not LEDGER_FILE.exists()
    df.to_csv(LEDGER_FILE, mode="w" if header else "a",
              header=header, index=False)


def find_latest_orders_file() -> Path:
    files = sorted(LIVE_DIR.glob("orders_*.csv"))
    if not files:
        raise FileNotFoundError(
            f"No orders_*.csv in {LIVE_DIR}. Run live/generate_orders.py first.")
    return files[-1]


def signal_date_of(orders_path: Path):
    """The close date the signal was computed from, parsed from the filename."""
    try:
        return pd.Timestamp(orders_path.stem.split("orders_", 1)[1])
    except Exception:
        return None


def check_fill_timing(signal_date, fill_date) -> bool:
    """
    Refuse a fill at an open that precedes the close which generated the signal.

    Returns True if the fill may proceed.
    """
    if signal_date is None or fill_date is None:
        print("  [WARN] Could not determine signal/fill dates — timing unchecked.")
        return True
    if fill_date > signal_date:
        delay = (fill_date - signal_date).days
        note = "" if delay <= 4 else f"   [note: {delay} calendar days late]"
        print(f"  Fill timing   : OK — signal {signal_date.date()}, "
              f"fill at {fill_date.date()} open{note}")
        return True

    bang = "!" * 74
    print()
    print(f"  {bang}")
    print(f"  REFUSING TO FILL. Signal date {signal_date.date()}, "
          f"fill date {fill_date.date()}.")
    print()
    print(f"  The order list was computed from the CLOSE of {signal_date.date()}.")
    print("  Filling at that same day's OPEN means buying six hours before the")
    print("  signal that chose the name existed. On the current order list that")
    print("  look-ahead measured -5.3 bps of 'slippage' — it reads as free money,")
    print("  and it is the exact failure this phase exists to catch.")
    print()
    print("  Run this the NEXT trading morning instead.")
    print(f"  {bang}")
    return False


def fetch_live_quotes(smart, symbols: list) -> dict:
    """Read-only LTP/open quotes from SmartAPI. No orders are placed."""
    quotes = {}
    tokens = resolve_tokens(symbols)
    print(f"\nFetching live quotes for {len(symbols)} symbols via SmartAPI...")
    for sym in symbols:
        token = tokens.get(sym)
        if not token:
            print(f"  [WARN] Scrip token not found for {sym}")
            continue
        try:
            res = smart.ltpData("NSE", f"{sym}-EQ", token)
            if res and res.get("status") and res.get("data"):
                data = res["data"]
                ltp = float(data.get("ltp", 0))
                open_px = float(data.get("open", ltp))
                if ltp > 0:
                    quotes[sym] = {"ltp": ltp,
                                   "open": open_px if open_px > 0 else ltp,
                                   "source": "smartapi_live"}
            else:
                print(f"  [WARN] Empty quote response for {sym}")
        except Exception as e:
            print(f"  [ERROR] Quote fetch failed for {sym}: {e}")
    return quotes


def execute_paper_trades(orders_df: pd.DataFrame, quotes: dict, pos: dict,
                         fill_price_key: str = "open",
                         signal_date=None, fill_date=None) -> tuple:
    """
    Simulate fills, charge delivery costs, and record realised slippage.

    Sells run first so their proceeds fund the buys — the order they would
    execute in live, and the reason cash never has to go negative.
    """
    executed = []
    cash = float(pos.get("cash", 0.0))
    holdings = dict(pos.get("holdings", {}))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sig = str(signal_date.date()) if signal_date is not None else ""
    fil = str(fill_date.date()) if fill_date is not None else ""

    print("\n" + "=" * 92)
    print("  SIMULATED FILL EXECUTION & SLIPPAGE AUDIT")
    print("=" * 92)
    print(f"{'Symbol':<12} {'Action':<6} {'Qty':>6} {'Ref Px':>10} {'Fill Px':>10} "
          f"{'Slippage':>11} {'Cost (Rs)':>10}")
    print("-" * 92)

    act = orders_df["action"].astype(str).str.upper()
    sell_orders = orders_df[act == "SELL"]
    buy_orders = orders_df[act == "BUY"]

    def record(sym, side, qty, ref, fill, slip, value, cost, reason, src):
        return {"timestamp": stamp, "signal_date": sig, "fill_date": fil,
                "symbol": sym, "action": side, "qty": qty,
                "ref_price": ref, "fill_price": fill,
                "slippage_bps": round(slip, 2), "traded_value": round(value, 2),
                "cost_inr": round(cost, 2), "reason": reason, "source": src}

    for _, order in sell_orders.iterrows():
        sym = order["symbol"]
        ref_price = float(order["ref_price"])
        quote = quotes.get(sym, {})
        fill_price = quote.get(fill_price_key) or quote.get("ltp") or ref_price

        # Never sell more than is held. Without this clamp the book books
        # proceeds for shares it does not own — a naked short that invents cash.
        held_qty = int(holdings.get(sym, 0))
        asked = int(order["qty"])
        qty = min(asked, held_qty)
        if qty <= 0:
            print(f"{sym:<12} {'SELL':<6} {0:>6} {ref_price:>10.2f} "
                  f"{fill_price:>10.2f}   [SKIPPED: not held]")
            continue
        if qty < asked:
            print(f"  [WARN] {sym}: order says sell {asked}, only {held_qty} "
                  f"held — selling {qty}.")

        slippage_bps = ((ref_price - fill_price) / ref_price) * 1e4 if ref_price > 0 else 0.0
        proceeds = qty * fill_price
        cost = delivery_one_way_cost(proceeds, "sell", slippage_per_leg=0.0)

        cash += proceeds - cost
        if held_qty - qty <= 0:
            holdings.pop(sym, None)
        else:
            holdings[sym] = held_qty - qty

        executed.append(record(sym, "SELL", qty, ref_price, fill_price,
                               slippage_bps, proceeds, cost,
                               order.get("reason", "rebalance_exit"),
                               quote.get("source", "mock")))
        print(f"{sym:<12} {'SELL':<6} {qty:>6} {ref_price:>10.2f} "
              f"{fill_price:>10.2f} {slippage_bps:>+10.1f}bp {cost:>10.2f}")

    for _, order in buy_orders.iterrows():
        sym = order["symbol"]
        ref_price = float(order["ref_price"])
        quote = quotes.get(sym, {})
        fill_price = quote.get(fill_price_key) or quote.get("ltp") or ref_price
        if not np.isfinite(fill_price) or fill_price <= 0:
            continue

        slippage_bps = ((fill_price - ref_price) / ref_price) * 1e4 if ref_price > 0 else 0.0

        # Size down to what cash allows. Jump straight to the affordable share
        # count rather than decrementing one at a time — a Rs.14 stock would
        # otherwise take thousands of iterations.
        qty = int(order["qty"])
        while qty >= 1:
            notional = qty * fill_price
            cost = delivery_one_way_cost(notional, "buy", slippage_per_leg=0.0)
            if notional + cost <= cash:
                break
            qty = min(qty - 1, int(cash / fill_price))
        if qty < 1:
            print(f"{sym:<12} {'BUY':<6} {0:>6} {ref_price:>10.2f} "
                  f"{fill_price:>10.2f}   [SKIPPED: insufficient cash]")
            continue

        notional = qty * fill_price
        cost = delivery_one_way_cost(notional, "buy", slippage_per_leg=0.0)
        cash -= notional + cost
        holdings[sym] = holdings.get(sym, 0) + qty

        executed.append(record(sym, "BUY", qty, ref_price, fill_price,
                               slippage_bps, notional, cost,
                               order.get("reason", "rebalance_entry"),
                               quote.get("source", "mock")))
        print(f"{sym:<12} {'BUY':<6} {qty:>6} {ref_price:>10.2f} "
              f"{fill_price:>10.2f} {slippage_bps:>+10.1f}bp {cost:>10.2f}")

    print("=" * 92)

    updated = {"as_of": fil or datetime.now().strftime("%Y-%m-%d"),
               "capital": float(pos.get("capital", DEFAULT_CAPITAL)),
               "cash": round(cash, 2),
               "holdings": holdings,
               "last_updated": stamp}
    return executed, updated


def main():
    ap = argparse.ArgumentParser(description="Local paper broker (Phase 2)")
    ap.add_argument("--orders", default=None,
                    help="Orders CSV (default: latest in live/)")
    ap.add_argument("--mock", action="store_true",
                    help="Synthetic quotes — tests wiring, measures nothing")
    ap.add_argument("--slippage-bps", type=float, default=5.0,
                    help="Synthetic slippage for --mock (default 5.0)")
    ap.add_argument("--fill-on", default="open", choices=["open", "ltp"],
                    help="Quote field to fill on (default: open)")
    ap.add_argument("--capital", type=float, default=DEFAULT_CAPITAL,
                    help="Starting virtual capital on the very first run")
    args = ap.parse_args()

    orders_path = Path(args.orders) if args.orders else find_latest_orders_file()
    print("=" * 92)
    print("  PAPER BROKER — simulated fills, no live orders")
    print("=" * 92)
    print(f"  Orders file   : {orders_path.name}")

    orders_df = pd.read_csv(orders_path)
    if orders_df.empty:
        print("  Orders file is empty. Nothing to execute.")
        return

    pos = load_positions(args.capital)
    symbols = list(orders_df["symbol"].unique())
    sig_date = signal_date_of(orders_path)

    if args.mock:
        fill_date = sig_date + pd.Timedelta(days=1) if sig_date is not None else None
        print(f"  Mode          : MOCK — {args.slippage_bps:+.1f} bps synthetic "
              f"slippage.")
        print(f"                  Recovers exactly what it injects; this checks "
              f"wiring, not execution.")
        quotes = {}
        for _, row in orders_df.iterrows():
            ref = float(row["ref_price"])
            mult = (1 + args.slippage_bps / 1e4) \
                if str(row["action"]).upper() == "BUY" \
                else (1 - args.slippage_bps / 1e4)
            px = round(ref * mult, 2)
            quotes[row["symbol"]] = {"open": px, "ltp": px, "source": "mock"}
    else:
        fill_date = pd.Timestamp(datetime.now().date())
        if not check_fill_timing(sig_date, fill_date):
            return
        try:
            smart = authenticate(load_credentials())
            quotes = fetch_live_quotes(smart, symbols)
        except Exception as e:
            print(f"\n  [ERROR] SmartAPI auth/quote fetch failed: {e}")
            print("  For an offline wiring test: python live/paper_broker.py --mock")
            return
        if not quotes:
            print("\n  [ERROR] No quotes returned. Nothing filled.")
            return

    print(f"  Opening cash  : Rs.{pos['cash']:,.2f}")

    executed, updated = execute_paper_trades(
        orders_df, quotes, pos, fill_price_key=args.fill_on,
        signal_date=sig_date, fill_date=fill_date)

    if not executed:
        print("\n  Nothing executed. State unchanged.")
        return

    append_to_ledger(executed)
    save_positions(updated)

    traded = sum(t["traded_value"] for t in executed)
    costs = sum(t["cost_inr"] for t in executed)
    slip = float(np.mean([t["slippage_bps"] for t in executed]))

    print("\n  Execution summary")
    print(f"    Trades        : {len(executed)}")
    print(f"    Traded value  : Rs.{traded:,.2f}")
    print(f"    Costs         : Rs.{costs:,.2f} ({costs/traded*1e4:.1f} bps)")
    print(f"    Mean slippage : {slip:+.2f} bps  (backtest assumes +5.0)")
    if not args.mock:
        print("                    One rebalance of ~20 legs carries a standard")
        print("                    error near 25 bps — not a measurement yet.")
    print(f"    Cash left     : Rs.{updated['cash']:,.2f}")
    print(f"    Ledger        : {LEDGER_FILE.name}")


if __name__ == "__main__":
    main()
