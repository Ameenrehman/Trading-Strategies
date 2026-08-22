"""
Backtest runner for ORB strategy using Backtesting.py.

Loads CSV data, applies the accurate Indian cost model, runs the backtest,
and produces stats + HTML reports.
"""

import os
import sys
import argparse
from pathlib import Path
import pandas as pd
from backtesting import Backtest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.orb_strategy import ORBStrategy
from backtest.costs import per_side_commission, cost_as_fraction

RESULTS_DIR = Path(__file__).parent / "results"
# The 5-minute set lives in its own folder so the daily (delivery) data
# under data/daily/ stays cleanly separated from the intraday work.
DATA_DIR = PROJECT_ROOT / "data" / "intraday_5min"
DEFAULT_POSITION_SIZE = 50_000


def load_data(csv_path: str | Path) -> pd.DataFrame:
    """
    Load and prepare OHLCV data for Backtesting.py.

    Backtesting.py expects:
    - DatetimeIndex
    - Columns: Open, High, Low, Close, Volume (capitalized)
    """
    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.set_index("datetime")
    df = df.sort_index()
    df.columns = [c.capitalize() for c in df.columns]
    df = df.dropna()
    return df


def run_single_backtest(
    data: pd.DataFrame,
    symbol: str,
    cash: float = 100_000,
    position_size: float = DEFAULT_POSITION_SIZE,
    or_bars: int = 6,
    rr_ratio: float = 2.0,
    min_range_pct: float = 0.0,
    max_entry_time: int = 750,
    use_atr_stop: bool = False,
    atr_mult: float = 1.5,
    allow_long: bool = True,
    allow_short: bool = True,
    save_html: bool = True,
) -> dict:
    """Run ORB backtest on a single stock's data with accurate commission."""
    # Per-side commission for Backtesting.py
    commission = per_side_commission(position_size)

    bt = Backtest(
        data,
        ORBStrategy,
        cash=cash,
        commission=commission,
        exclusive_orders=True,
        trade_on_close=True,
    )

    stats = bt.run(
        or_bars=or_bars,
        rr_ratio=rr_ratio,
        min_range_pct=min_range_pct,
        max_entry_time=max_entry_time,
        use_atr_stop=use_atr_stop,
        atr_mult=atr_mult,
        allow_long=allow_long,
        allow_short=allow_short,
    )

    if save_html:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        html_path = RESULTS_DIR / f"{symbol}_orb_report.html"
        try:
            bt.plot(filename=str(html_path), open_browser=False)
            print(f"  HTML report saved: {html_path}")
        except Exception as e:
            print(f"  [Notice] HTML plot skipped: {e}")

    return stats


def print_stats(stats, symbol: str):
    """Print key backtest statistics."""
    print(f"\n{'='*60}")
    print(f"  ORB Backtest Results: {symbol}")
    print(f"{'='*60}")

    metrics = {
        "Start": str(stats.get("Start", "N/A")),
        "End": str(stats.get("End", "N/A")),
        "Duration": str(stats.get("Duration", "N/A")),
        "Return [%]": f"{stats.get('Return [%]', 0):.2f}%",
        "Buy & Hold Return [%]": f"{stats.get('Buy & Hold Return [%]', 0):.2f}%",
        "Sharpe Ratio": f"{stats.get('Sharpe Ratio', 0):.3f}",
        "Max Drawdown [%]": f"{stats.get('Max. Drawdown [%]', 0):.2f}%",
        "Win Rate [%]": f"{stats.get('Win Rate [%]', 0):.1f}%",
        "# Trades": stats.get("# Trades", 0),
        "Profit Factor": f"{stats.get('Profit Factor', 0):.3f}" if stats.get('Profit Factor') else "N/A",
        "Avg Trade [%]": f"{stats.get('Avg. Trade [%]', 0):.3f}%",
        "Expectancy [%]": f"{stats.get('Expectancy [%]', 0):.3f}%",
        "Equity Final": f"Rs.{stats.get('Equity Final [$]', 0):,.0f}",
        "Equity Peak": f"Rs.{stats.get('Equity Peak [$]', 0):,.0f}",
    }

    for key, val in metrics.items():
        print(f"  {key:30s}: {val}")


def run_all_stocks(
    or_bars: int = 6,
    rr_ratio: float = 2.0,
    min_range_pct: float = 0.0,
    max_entry_time: int = 750,
    use_atr_stop: bool = False,
    atr_mult: float = 1.5,
    allow_long: bool = True,
    allow_short: bool = True,
):
    """Run backtest across all available stock CSVs in data/."""
    csv_files = sorted(DATA_DIR.glob("*_5min.csv"))

    if not csv_files:
        print("[ERROR] No data files found in data/. Run data/fetch_historical.py first.")
        sys.exit(1)

    print(f"Found {len(csv_files)} data files.")
    print(f"Parameters: or_bars={or_bars}, rr_ratio={rr_ratio}, min_range={min_range_pct}%, "
          f"max_entry_time={max_entry_time}, use_atr_stop={use_atr_stop}, long={allow_long}, short={allow_short}")

    all_results = []

    for csv_path in csv_files:
        symbol = csv_path.stem.replace("_5min", "")
        print(f"\n--- Running backtest: {symbol} ---")

        data = load_data(csv_path)

        try:
            stats = run_single_backtest(
                data, symbol,
                or_bars=or_bars,
                rr_ratio=rr_ratio,
                min_range_pct=min_range_pct,
                max_entry_time=max_entry_time,
                use_atr_stop=use_atr_stop,
                atr_mult=atr_mult,
                allow_long=allow_long,
                allow_short=allow_short,
            )
            print_stats(stats, symbol)
            all_results.append({
                "symbol": symbol,
                "trades": stats.get("# Trades", 0),
                "return_pct": stats.get("Return [%]", 0),
                "sharpe": stats.get("Sharpe Ratio", 0),
                "max_dd_pct": stats.get("Max. Drawdown [%]", 0),
                "win_rate": stats.get("Win Rate [%]", 0),
                "profit_factor": stats.get("Profit Factor", 0),
                "avg_trade_pct": stats.get("Avg. Trade [%]", 0),
            })
        except Exception as e:
            print(f"  [ERROR] Backtest failed for {symbol}: {e}")
            import traceback
            traceback.print_exc()

    # Summary table
    if all_results:
        print(f"\n\n{'='*80}")
        print("  SUMMARY ACROSS ALL STOCKS")
        print(f"{'='*80}")
        summary_df = pd.DataFrame(all_results)
        print(summary_df.to_string(index=False))

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        summary_path = RESULTS_DIR / "orb_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ORB backtest")
    parser.add_argument("--or-bars", type=int, default=6, help="Opening range bars (default: 6 = 30 min)")
    parser.add_argument("--rr-ratio", type=float, default=2.0, help="Reward-to-risk ratio (default: 2.0)")
    parser.add_argument("--min-range", type=float, default=0.0, help="Min opening range %% (default: 0.0)")
    parser.add_argument("--max-time", type=int, default=750, help="Cutoff time in mins from midnight (default: 750 = 12:30 PM)")
    parser.add_argument("--use-atr", action="store_true", help="Use ATR stop instead of full range")
    parser.add_argument("--atr-mult", type=float, default=1.5, help="ATR multiplier (default: 1.5)")
    parser.add_argument("--long-only", action="store_true", help="Take long trades only")
    parser.add_argument("--short-only", action="store_true", help="Take short trades only")
    parser.add_argument("--symbol", type=str, default=None, help="Run for a single symbol only")

    args = parser.parse_args()

    allow_long = not args.short_only
    allow_short = not args.long_only

    if args.symbol:
        csv_path = DATA_DIR / f"{args.symbol}_5min.csv"
        if not csv_path.exists():
            print(f"[ERROR] Data file not found: {csv_path}")
            sys.exit(1)
        data = load_data(csv_path)
        stats = run_single_backtest(
            data, args.symbol,
            or_bars=args.or_bars,
            rr_ratio=args.rr_ratio,
            min_range_pct=args.min_range,
            max_entry_time=args.max_time,
            use_atr_stop=args.use_atr,
            atr_mult=args.atr_mult,
            allow_long=allow_long,
            allow_short=allow_short,
        )
        print_stats(stats, args.symbol)
    else:
        run_all_stocks(
            or_bars=args.or_bars,
            rr_ratio=args.rr_ratio,
            min_range_pct=args.min_range,
            max_entry_time=args.max_time,
            use_atr_stop=args.use_atr,
            atr_mult=args.atr_mult,
            allow_long=allow_long,
            allow_short=allow_short,
        )
