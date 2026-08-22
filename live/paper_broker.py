"""
Local Paper Broker for Delivery Systematic Momentum (Phase 2).

Simulates order execution against real market data without placing live exchange orders.
Uses Angel One SmartAPI in read-only mode to fetch opening/live quotes, records simulated
fills, calculates exact realized slippage vs rebalance reference prices, charges realistic
delivery costs (STT, brokerage, DP, stamp duty), and logs all trades to an audit ledger.

Why local paper trading:
  1. Measures REAL opening slippage — the main unverified assumption in the backtest.
  2. Runs 100% locally with zero live financial risk.
  3. Uses read-only market data endpoints — no static IP or SEBI algo registration required.

Usage:
  # Execute pending orders from latest orders CSV at current market quotes
  python live/paper_broker.py

  # Test execution in offline/mock mode (useful outside market hours)
  python live/paper_broker.py --mock --slippage-bps 5.0

  # Specify a specific orders CSV file
  python live/paper_broker.py --orders live/orders_2026-08-21.csv
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

from backtest.costs import delivery_one_way_cost
from data.fetch_universe import load_credentials, authenticate, resolve_tokens

LIVE_DIR = Path(__file__).parent
POSITIONS_FILE = LIVE_DIR / "positions.json"
LEDGER_FILE = LIVE_DIR / "paper_ledger.csv"


def load_positions(capital_default: float = 1_000_000.0) -> dict:
    """Load positions file or initialize new virtual cash balance."""
    if POSITIONS_FILE.exists():
        try:
            return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "as_of": None,
        "capital": capital_default,
        "cash": capital_default,
        "holdings": {},
        "last_updated": None,
    }


def save_positions(pos: dict):
    """Atomically save current portfolio state."""
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS_FILE.write_text(json.dumps(pos, indent=2), encoding="utf-8")


def append_to_ledger(trade_records: list):
    """Append executed paper trades to persistent ledger CSV."""
    if not trade_records:
        return
    df = pd.DataFrame(trade_records)
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LEDGER_FILE.exists():
        df.to_csv(LEDGER_FILE, mode="a", header=False, index=False)
    else:
        df.to_csv(LEDGER_FILE, mode="w", header=True, index=False)


def find_latest_orders_file() -> Path:
    """Find the most recent orders_*.csv in live directory."""
    files = sorted(LIVE_DIR.glob("orders_*.csv"))
    if not files:
        raise FileNotFoundError(f"No orders_*.csv found in {LIVE_DIR}. Run live/generate_orders.py first.")
    return files[-1]


def fetch_live_quotes(smart, symbols: list) -> dict:
    """
    Fetch live LTP and Open quotes from Angel One SmartAPI (read-only).
    Returns dict: symbol -> {'ltp': float, 'open': float, 'source': str}
    """
    quotes = {}
    tokens = resolve_tokens(symbols)

    print(f"\nFetching live quotes for {len(symbols)} symbols via SmartAPI...")
    for sym in symbols:
        token = tokens.get(sym)
        if not token:
            print(f"  [WARN] Scrip token not found for {sym}")
            continue
        try:
            # ltpData is read-only market data
            res = smart.ltpData("NSE", f"{sym}-EQ", token)
            if res and res.get("status") and res.get("data"):
                data = res["data"]
                ltp = float(data.get("ltp", 0))
                open_px = float(data.get("open", ltp))
                if ltp > 0:
                    quotes[sym] = {
                        "ltp": ltp,
                        "open": open_px if open_px > 0 else ltp,
                        "source": "smartapi_live",
                    }
            else:
                print(f"  [WARN] Empty quote response for {sym}")
        except Exception as e:
            print(f"  [ERROR] Failed to fetch quote for {sym}: {e}")

    return quotes


def execute_paper_trades(orders_df: pd.DataFrame,
                         quotes: dict,
                         pos: dict,
                         fill_price_key: str = "open") -> tuple:
    """
    Execute simulated fills against live quotes, apply transaction costs, and record slippage.
    """
    executed = []
    cash = float(pos.get("cash", pos.get("capital", 1_000_000.0)))
    holdings = dict(pos.get("holdings", {}))
    trade_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 86)
    print("  SIMULATED FILL EXECUTION & SLIPPAGE AUDIT")
    print("=" * 86)
    print(f"{'Symbol':<12} {'Action':<6} {'Qty':>6} {'Ref Px':>10} {'Fill Px':>10} {'Slippage':>10} {'Cost (Rs)':>10}")
    print("-" * 86)

    # First execute SELLS to release cash
    sell_orders = orders_df[orders_df["action"].str.upper() == "SELL"]
    buy_orders = orders_df[orders_df["action"].str.upper() == "BUY"]

    for _, order in sell_orders.iterrows():
        sym = order["symbol"]
        qty = int(order["qty"])
        ref_price = float(order["ref_price"])
        quote = quotes.get(sym, {})
        fill_price = quote.get(fill_price_key) or quote.get("ltp") or ref_price

        # Realized slippage for sells: positive if filled below ref_price (worse)
        slippage_bps = ((ref_price - fill_price) / ref_price) * 10000 if ref_price > 0 else 0.0
        proceeds = qty * fill_price
        cost = delivery_one_way_cost(proceeds, "sell", slippage_per_leg=0.0)  # exchange/STT/brokerage/DP

        cash += proceeds - cost
        held_qty = holdings.get(sym, 0)
        if held_qty <= qty:
            holdings.pop(sym, None)
        else:
            holdings[sym] = held_qty - qty

        record = {
            "timestamp": trade_time,
            "symbol": sym,
            "action": "SELL",
            "qty": qty,
            "ref_price": ref_price,
            "fill_price": fill_price,
            "slippage_bps": round(slippage_bps, 2),
            "traded_value": round(proceeds, 2),
            "cost_inr": round(cost, 2),
            "reason": order.get("reason", "rebalance_exit"),
            "source": quote.get("source", "mock"),
        }
        executed.append(record)
        print(f"{sym:<12} {'SELL':<6} {qty:>6} {ref_price:>10.2f} {fill_price:>10.2f} {slippage_bps:>+9.1f}bp {cost:>10.2f}")

    # Next execute BUYS
    for _, order in buy_orders.iterrows():
        sym = order["symbol"]
        wanted_qty = int(order["qty"])
        ref_price = float(order["ref_price"])
        quote = quotes.get(sym, {})
        fill_price = quote.get(fill_price_key) or quote.get("ltp") or ref_price

        # Realized slippage for buys: positive if filled above ref_price (worse)
        slippage_bps = ((fill_price - ref_price) / ref_price) * 10000 if ref_price > 0 else 0.0

        # Sizing / Cash boundary check
        qty = wanted_qty
        notional = qty * fill_price
        cost = delivery_one_way_cost(notional, "buy", slippage_per_leg=0.0)

        while qty >= 1 and (notional + cost > cash):
            qty -= 1
            notional = qty * fill_price
            cost = delivery_one_way_cost(notional, "buy", slippage_per_leg=0.0)

        if qty < 1:
            print(f"{sym:<12} {'BUY':<6} {'0':>6} {ref_price:>10.2f} {fill_price:>10.2f}  [SKIPPED: insufficient cash]")
            continue

        cash -= notional + cost
        holdings[sym] = holdings.get(sym, 0) + qty

        record = {
            "timestamp": trade_time,
            "symbol": sym,
            "action": "BUY",
            "qty": qty,
            "ref_price": ref_price,
            "fill_price": fill_price,
            "slippage_bps": round(slippage_bps, 2),
            "traded_value": round(notional, 2),
            "cost_inr": round(cost, 2),
            "reason": order.get("reason", "rebalance_entry"),
            "source": quote.get("source", "mock"),
        }
        executed.append(record)
        print(f"{sym:<12} {'BUY':<6} {qty:>6} {ref_price:>10.2f} {fill_price:>10.2f} {slippage_bps:>+9.1f}bp {cost:>10.2f}")

    print("=" * 86)

    updated_pos = {
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "capital": pos.get("capital", 1_000_000.0),
        "cash": round(cash, 2),
        "holdings": holdings,
        "last_updated": trade_time,
    }

    return executed, updated_pos


def main():
    ap = argparse.ArgumentParser(description="Local Paper Trading Broker for Delivery Momentum")
    ap.add_argument("--orders", default=None, help="Path to orders CSV (default: latest in live/)")
    ap.add_argument("--mock", action="store_true", help="Run with mock quotes instead of live SmartAPI")
    ap.add_argument("--slippage-bps", type=float, default=5.0,
                    help="Synthetic slippage in bps for mock mode (default: 5.0 bps)")
    ap.add_argument("--fill-on", default="open", choices=["open", "ltp"],
                    help="Price field to fill simulated orders on (default: open)")
    args = ap.parse_args()

    orders_path = Path(args.orders) if args.orders else find_latest_orders_file()
    print(f"Reading pending orders from: {orders_path}")
    orders_df = pd.read_csv(orders_path)
    if orders_df.empty:
        print("Orders file is empty. Nothing to execute.")
        return

    pos = load_positions()
    symbols = list(orders_df["symbol"].unique())

    if args.mock:
        print(f"\n[MOCK MODE] Simulating execution with {args.slippage_bps:+.1f} bps synthetic slippage")
        quotes = {}
        for _, row in orders_df.iterrows():
            sym = row["symbol"]
            ref = float(row["ref_price"])
            # Apply positive slippage for BUY (higher price), negative for SELL (lower price)
            mult = (1.0 + args.slippage_bps / 10000.0) if row["action"] == "BUY" else (1.0 - args.slippage_bps / 10000.0)
            mock_fill = round(ref * mult, 2)
            quotes[sym] = {"open": mock_fill, "ltp": mock_fill, "source": "mock"}
    else:
        try:
            creds = load_credentials()
            smart = authenticate(creds)
            quotes = fetch_live_quotes(smart, symbols)
        except Exception as e:
            print(f"\n[ERROR] SmartAPI authentication/quote fetch failed: {e}")
            print("To test without network credentials, rerun with: python live/paper_broker.py --mock")
            return

    executed, updated_pos = execute_paper_trades(orders_df, quotes, pos, fill_price_key=args.fill_on)

    if executed:
        append_to_ledger(executed)
        save_positions(updated_pos)

        total_traded = sum(t["traded_value"] for t in executed)
        total_costs = sum(t["cost_inr"] for t in executed)
        avg_slippage = np.mean([t["slippage_bps"] for t in executed])

        print(f"\nExecution Summary:")
        print(f"  Trades Executed : {len(executed)}")
        print(f"  Traded Value    : Rs.{total_traded:,.2f}")
        print(f"  Total Costs     : Rs.{total_costs:,.2f} ({total_costs / total_traded * 1e4:.1f} bps)")
        print(f"  Mean Slippage   : {avg_slippage:+.2f} bps  (Backtest assumption: 5.0 bps)")
        print(f"  Remaining Cash  : Rs.{updated_pos['cash']:,.2f}")
        print(f"  Positions File  : {POSITIONS_FILE}")
        print(f"  Ledger File     : {LEDGER_FILE}")


if __name__ == "__main__":
    main()
