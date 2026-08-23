"""
Controls for the momentum result — does the RANKING actually add anything?

This is the direct analog of the randomized-direction control that decided the
intraday work. There, the real strategy beat 20/20 random-direction seeds while
the inverted variant was symmetrically negative, which is what distinguished a
genuine edge from a volatility artifact. That test was the single most valuable
thing in Phase 1, so it is built in here from the start rather than bolted on.

The alternative explanation to kill: momentum "works" only because it ends up
holding whatever has gone up, in a market that rises. If picking 20 names at
random from the same eligible, in-trend universe does just as well, the ranking
is adding nothing and the apparent edge is just equity beta plus the trend
filter.

  Control A - random selection. Same universe, same eligibility and trend
  filter, same equal weighting, same costs, same rebalance dates. Only the
  choice of which 20 names is randomised. 20 seeds.

  Control B - bottom decile. Hold the WORST names by momentum rank. A real
  effect shows the mirror pattern: top beats random, bottom is symmetrically
  worse.

Usage:
    python backtest/test_momentum_controls.py
    python backtest/test_momentum_controls.py --seeds 20
"""

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import run_portfolio, load_daily
from strategies.momentum_xs import (MomentumConfig, make_signal_fn,
                                    make_random_signal_fn, make_bottom_signal_fn,
                                    make_buyhold_signal_fn)

warnings.filterwarnings("ignore")
RESULTS_DIR = Path(__file__).parent / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--data-dir", default=None,
                    help="Directory of *_1day.csv files (default: data/daily)")
    args = ap.parse_args()

    closes, volumes, ca_events = load_daily(
        Path(args.data_dir) if args.data_dir else None, report=True)
    if ca_events:
        from data.corporate_actions import format_events
        print("Unadjusted corporate actions repaired before ranking:")
        print(format_events(ca_events))
        print()
    cfg = MomentumConfig()
    cap = args.capital

    print(f"Universe: {closes.shape[1]} symbols, "
          f"{closes.index[0].date()} -> {closes.index[-1].date()}\n")

    print("Running the real strategy...")
    real = run_portfolio(closes, make_signal_fn(cfg, volumes),
                         initial_capital=cap, rebalance="ME")["stats"]

    print("Running the benchmark...")
    bench = run_portfolio(closes, make_buyhold_signal_fn(cfg, volumes),
                          initial_capital=cap, rebalance="ME")["stats"]

    print(f"Running control A (random selection) x {args.seeds} seeds...")
    ctrl = []
    for s in range(args.seeds):
        r = run_portfolio(closes, make_random_signal_fn(cfg, volumes, s),
                          initial_capital=cap, rebalance="ME")["stats"]
        ctrl.append(r)
        print(f"  seed {s:>2}: CAGR {r['cagr_pct']:>6.2f}%  Sharpe {r['sharpe']:>5.2f}")

    print("Running control B (bottom decile)...")
    bottom = run_portfolio(closes, make_bottom_signal_fn(cfg, volumes),
                           initial_capital=cap, rebalance="ME")["stats"]

    cg = np.array([c["cagr_pct"] for c in ctrl])
    cs = np.array([c["sharpe"] for c in ctrl])

    print("\n" + "=" * 84)
    print("  CONTROL TEST — does the momentum RANKING carry information?")
    print("=" * 84)
    print(f"  {'':34s} {'CAGR%':>8} {'Sharpe':>8} {'maxDD%':>9}")
    print("  " + "-" * 66)
    print(f"  {'REAL (top 20 by momentum)':34s} {real['cagr_pct']:>8.2f} "
          f"{real['sharpe']:>8.2f} {real['max_dd_pct']:>9.1f}")
    print(f"  {'BENCHMARK (equal-weight B&H)':34s} {bench['cagr_pct']:>8.2f} "
          f"{bench['sharpe']:>8.2f} {bench['max_dd_pct']:>9.1f}")
    print(f"  {'Control A random (mean)':34s} {cg.mean():>8.2f} "
          f"{cs.mean():>8.2f} {np.mean([c['max_dd_pct'] for c in ctrl]):>9.1f}")
    print(f"  {'  ... best of ' + str(args.seeds) + ' seeds':34s} {cg.max():>8.2f} "
          f"{cs.max():>8.2f}")
    print(f"  {'  ... worst of ' + str(args.seeds) + ' seeds':34s} {cg.min():>8.2f} "
          f"{cs.min():>8.2f}")
    print(f"  {'Control B bottom decile':34s} {bottom['cagr_pct']:>8.2f} "
          f"{bottom['sharpe']:>8.2f} {bottom['max_dd_pct']:>9.1f}")

    beat = int((cg >= real["cagr_pct"]).sum())
    print()
    print(f"  Random seeds matching or beating the real strategy: {beat}/{len(cg)}")
    print(f"  Real vs random mean : {real['cagr_pct'] - cg.mean():+.2f}%/yr")
    print(f"  Random mean vs bottom: {cg.mean() - bottom['cagr_pct']:+.2f}%/yr")

    symmetric = (real["cagr_pct"] > cg.mean() > bottom["cagr_pct"])
    print()
    if beat == 0 and symmetric:
        print("  VERDICT: the ranking carries information. Momentum beats every")
        print("           random seed AND the bottom decile is symmetrically worse —")
        print("           the mirror pattern that indicates a real effect rather")
        print("           than equity beta plus a trend filter.")
    elif beat <= 1 and symmetric:
        print("  VERDICT: suggestive. The mirror pattern is there but the margin")
        print("           over random selection is not decisive at this sample size.")
    else:
        print("  VERDICT: NOT SUPPORTED. Random selection from the same eligible,")
        print("           in-trend universe does about as well. The apparent edge is")
        print("           the trend filter and equity beta, not the momentum ranking.")

    out = pd.DataFrame(
        [{"variant": "real", **real}, {"variant": "benchmark", **bench},
         {"variant": "bottom_decile", **bottom}]
        + [{"variant": f"random_seed_{i}", **c} for i, c in enumerate(ctrl)])
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(RESULTS_DIR / "momentum_controls.csv", index=False)
    print(f"\nSaved: {RESULTS_DIR / 'momentum_controls.csv'}")


if __name__ == "__main__":
    main()
