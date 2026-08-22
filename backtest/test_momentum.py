"""
Cross-sectional momentum vs buy-and-hold, after realistic delivery costs.

The bar is NOT "does it make money". A long-only equity strategy making money
proves nothing — the market rises. The bar is beating equal-weight buy-and-hold
of the same universe, after costs, by enough to survive survivorship bias.

Pre-registered go/no-go (Learning-T/phase-1b-delivery-momentum.md):
  1. Beats benchmark by >= 3%/yr CAGR after costs
  2. Higher Sharpe, and max drawdown no worse
  3. Beats >= 19 of 20 random-selection seeds     (test_momentum_controls.py)
  4. Bottom-decile control clearly worse           (test_momentum_controls.py)
  5. Survives walk-forward without re-fitting
  6. Holds up in the recent-5-year subsample

The 3%/yr margin is not arbitrary: applying today's index membership to years
of history excludes companies that failed, and that bias is plausibly worth
~2%/yr. Anything under 3% is not established.

Usage:
    python backtest/test_momentum.py
    python backtest/test_momentum.py --capital 1000000 --quick
"""

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import run_portfolio, load_daily
from strategies.momentum_xs import (MomentumConfig, make_signal_fn,
                                    make_buyhold_signal_fn, above_trend)

warnings.filterwarnings("ignore")
RESULTS_DIR = Path(__file__).parent / "results"


def fmt(stats, label):
    return {
        "variant": label,
        "years": stats.get("years", np.nan),
        "CAGR%": stats.get("cagr_pct", np.nan),
        "vol%": stats.get("vol_pct", np.nan),
        "Sharpe": stats.get("sharpe", np.nan),
        "maxDD%": stats.get("max_dd_pct", np.nan),
        "Calmar": stats.get("calmar", np.nan),
        "turn/yr%": stats.get("annual_turnover_pct", np.nan),
        "hold(mo)": stats.get("avg_hold_months", np.nan),
        "cost%/yr": stats.get("cost_drag_pct_yr", np.nan),
        "final": stats.get("final_equity", np.nan),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--data-dir", default=None,
                    help="Directory of *_1day.csv files (default: data/daily)")
    ap.add_argument("--quick", action="store_true",
                    help="Baseline and benchmark only, skip the variant sweep")
    args = ap.parse_args()

    closes, volumes = load_daily(Path(args.data_dir) if args.data_dir else None)
    print(f"Universe: {closes.shape[1]} symbols")
    print(f"History : {closes.index[0].date()} -> {closes.index[-1].date()} "
          f"({(closes.index[-1] - closes.index[0]).days / 365.25:.1f} years)")
    print(f"Capital : Rs.{args.capital:,.0f}\n")

    base = MomentumConfig()
    rows = []
    variants = 0

    # --- benchmark: equal-weight buy-and-hold of the eligible universe ------
    print("Running benchmark (equal-weight buy & hold)...")
    bench = run_portfolio(closes, make_buyhold_signal_fn(base, volumes),
                          initial_capital=args.capital, rebalance="ME")
    rows.append(fmt(bench["stats"], "BENCHMARK equal-weight B&H"))

    # --- the strategy -------------------------------------------------------
    print("Running momentum baseline (12-1, top 20, 200-DMA filter)...")
    mom = run_portfolio(closes, make_signal_fn(base, volumes),
                        initial_capital=args.capital, rebalance="ME")
    rows.append(fmt(mom["stats"], "momentum 12-1 top20 +200DMA"))
    variants += 1

    if not args.quick:
        print("Sweeping variants...")
        sweep = [
            ("no trend filter", MomentumConfig(trend_ma=0), "ME"),
            ("top 10", MomentumConfig(n_positions=10), "ME"),
            ("top 30", MomentumConfig(n_positions=30), "ME"),
            ("6-1 momentum", MomentumConfig(lookback_days=126), "ME"),
            ("quarterly rebalance", MomentumConfig(), "QE"),
            ("rank buffer 10", MomentumConfig(exit_rank_buffer=10), "ME"),
        ]
        for label, cfg, freq in sweep:
            r = run_portfolio(closes, make_signal_fn(cfg, volumes),
                              initial_capital=args.capital, rebalance=freq)
            rows.append(fmt(r["stats"], label))
            variants += 1

        # Exit-rule variants — these answer "should there be a stop loss?"
        print("Testing exit-rule variants (stop loss / daily trend exit)...")
        for label, kw in [
            ("+ disaster stop -25%", dict(disaster_stop_pct=0.25)),
            ("+ daily trend exit", dict(trend_exit_fn=lambda c, d: above_trend(c, d, base))),
        ]:
            r = run_portfolio(closes, make_signal_fn(base, volumes),
                              initial_capital=args.capital, rebalance="ME", **kw)
            rows.append(fmt(r["stats"], label))
            variants += 1

        # --- rebalance frequency: how often should the list be refreshed? ---
        # The question is not "daily or monthly" but "how much turnover does
        # checking more often actually create". A 12-month momentum score moves
        # slowly, so frequent checking mostly churns names oscillating across
        # the top-N boundary — which a rank buffer fixes far more cheaply than
        # a slower calendar does. Read the turnover% and cost%/yr columns here,
        # not just CAGR.
        print("Sweeping rebalance frequency (daily / weekly / monthly)...")
        for label, freq, cfg in [
            ("DAILY rebalance", "D", MomentumConfig()),
            ("DAILY + rank buffer 10", "D", MomentumConfig(exit_rank_buffer=10)),
            ("DAILY + rank buffer 20", "D", MomentumConfig(exit_rank_buffer=20)),
            ("WEEKLY rebalance", "W", MomentumConfig()),
            ("WEEKLY + rank buffer 10", "W", MomentumConfig(exit_rank_buffer=10)),
        ]:
            r = run_portfolio(closes, make_signal_fn(cfg, volumes),
                              initial_capital=args.capital, rebalance=freq)
            rows.append(fmt(r["stats"], label))
            variants += 1

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print("\n" + "=" * 120)
    print("  CROSS-SECTIONAL MOMENTUM — full history, after delivery costs")
    print("=" * 120)
    print(df.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    # --- the survivorship-bias check: recent window vs full window ----------
    recent_start = closes.index[-1] - pd.Timedelta(days=int(5 * 365.25))
    if closes.index[0] < recent_start:
        print("\n" + "=" * 120)
        print("  RECENT 5 YEARS — index membership drift is smallest here.")
        print("  A big gap vs the full window is a survivorship-bias signature.")
        print("=" * 120)
        rrows = []
        b5 = run_portfolio(closes, make_buyhold_signal_fn(base, volumes),
                           initial_capital=args.capital, rebalance="ME",
                           start=recent_start)
        rrows.append(fmt(b5["stats"], "BENCHMARK equal-weight B&H"))
        m5 = run_portfolio(closes, make_signal_fn(base, volumes),
                           initial_capital=args.capital, rebalance="ME",
                           start=recent_start)
        rrows.append(fmt(m5["stats"], "momentum 12-1 top20 +200DMA"))
        r5 = pd.DataFrame(rrows)
        print(r5.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
        edge5 = m5["stats"]["cagr_pct"] - b5["stats"]["cagr_pct"]
    else:
        edge5 = np.nan

    # --- verdict ------------------------------------------------------------
    edge = mom["stats"]["cagr_pct"] - bench["stats"]["cagr_pct"]
    dd_ok = mom["stats"]["max_dd_pct"] >= bench["stats"]["max_dd_pct"]
    sharpe_ok = mom["stats"]["sharpe"] > bench["stats"]["sharpe"]

    print("\n" + "=" * 120)
    print("  GO / NO-GO (criteria 1, 2, 6 — controls are in test_momentum_controls.py)")
    print("=" * 120)
    print(f"  1. Beats benchmark by >= 3%/yr : {edge:+.2f}%/yr  "
          f"[{'PASS' if edge >= 3 else 'FAIL'}]")
    print(f"  2a. Higher Sharpe              : {mom['stats']['sharpe']:.2f} vs "
          f"{bench['stats']['sharpe']:.2f}  [{'PASS' if sharpe_ok else 'FAIL'}]")
    print(f"  2b. Max drawdown no worse      : {mom['stats']['max_dd_pct']:.1f}% vs "
          f"{bench['stats']['max_dd_pct']:.1f}%  [{'PASS' if dd_ok else 'FAIL'}]")
    if np.isfinite(edge5):
        print(f"  6. Recent-5y edge              : {edge5:+.2f}%/yr  "
              f"[{'PASS' if edge5 >= 3 else 'FAIL'}]")
    print(f"\n  Variants tested this run: {variants} "
          f"(count them against the multiple-testing budget)")
    print(f"  Annualised turnover: {mom['stats']['annual_turnover_pct']:.0f}%/yr "
          f"-> avg hold ~{mom['stats']['avg_hold_months']:.1f} months")
    print(f"  Turnover is the dominant cost lever — compare turn/yr% across the")
    print(f"  rebalance-frequency rows before choosing a schedule.")
    print("\n  NOTE: returns are price-only (no dividends). This understates the")
    print("  strategy and the benchmark roughly equally, so the comparison holds.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / "momentum_summary.csv", index=False)
    mom["equity"].to_csv(RESULTS_DIR / "momentum_equity.csv")
    bench["equity"].to_csv(RESULTS_DIR / "benchmark_equity.csv")
    print(f"\nSaved: {RESULTS_DIR / 'momentum_summary.csv'}")


if __name__ == "__main__":
    main()
