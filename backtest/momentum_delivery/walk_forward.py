"""
Walk-forward validation — criterion 5.

Two separate questions, which are easy to conflate:

  A. STABILITY (no fitting at all). The baseline configuration was written down
     before any data was seen. Run it over sequential out-of-sample windows and
     ask whether the edge is present throughout, or whether one or two windows
     carry the entire full-period result. A 15-year CAGR is a single number and
     a single number can hide almost anything.

  B. SELECTION (the real overfitting test). 14 variants have now been tried on
     this data. If picking the best-so-far variant on a training window then
     beats the fixed baseline on the NEXT window, the sweep found something. If
     it does worse, the sweep was fitting noise and the pre-registered baseline
     is the honest configuration to trade.

Test B is the one that can change a decision. Test A can only fail to reassure.

Both run on the development period only — `split_holdout()` removes the
trailing 24 months. That window was already observed once by the first
real-data run (see HOLDOUT_MONTHS in portfolio.py), which is a process failure
worth not repeating.

Run:
    python backtest/walk_forward.py
    python backtest/walk_forward.py --test-years 1 --min-train-years 4
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import (run_portfolio, load_daily, split_holdout,
                                HOLDOUT_MONTHS)
from strategies.momentum_xs import (MomentumConfig, make_signal_fn,
                                    make_buyhold_signal_fn)

RESULTS_DIR = PROJECT_ROOT / "backtest" / "results"

# The candidate set whose SELECTION is under test. Deliberately the same list
# swept in test_momentum.py — testing selection over a different set would not
# tell us anything about the sweep we actually ran.
CANDIDATES = [
    ("baseline 12-1 top20 +200DMA", MomentumConfig(), "ME"),
    ("no trend filter",             MomentumConfig(trend_ma=0), "ME"),
    ("top 10",                      MomentumConfig(n_positions=10), "ME"),
    ("top 30",                      MomentumConfig(n_positions=30), "ME"),
    ("6-1 momentum",                MomentumConfig(lookback_days=126), "ME"),
    ("quarterly rebalance",         MomentumConfig(), "QE"),
    ("rank buffer 10",              MomentumConfig(exit_rank_buffer=10), "ME"),
    ("DAILY + rank buffer 10",      MomentumConfig(exit_rank_buffer=10), "D"),
    ("DAILY + rank buffer 20",      MomentumConfig(exit_rank_buffer=20), "D"),
    ("WEEKLY + rank buffer 10",     MomentumConfig(exit_rank_buffer=10), "W"),
    ("WEEKLY rebalance",            MomentumConfig(), "W"),
]


def run_window(closes, volumes, cfg, rebal, start, end):
    """One backtest over [start, end]. Returns stats, or None if it can't run."""
    try:
        r = run_portfolio(closes, make_signal_fn(cfg, volumes),
                          initial_capital=1_000_000, rebalance=rebal,
                          start=start, end=end)
    except Exception:
        return None
    st = r.get("stats") or {}
    return st if np.isfinite(st.get("cagr_pct", np.nan)) else None


def benchmark_window(closes, volumes, start, end):
    r = run_portfolio(closes, make_buyhold_signal_fn(MomentumConfig(), volumes),
                      initial_capital=1_000_000, rebalance="ME",
                      start=start, end=end)
    return r["stats"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-years", type=float, default=1.0,
                    help="Length of each out-of-sample window")
    ap.add_argument("--min-train-years", type=float, default=4.0,
                    help="Training history required before the first OOS window")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()

    closes_all, volumes_all = load_daily(
        Path(args.data_dir) if args.data_dir else None)
    closes, volumes, cutoff = split_holdout(closes_all, volumes_all)

    print("=" * 100)
    print("  WALK-FORWARD VALIDATION — criterion 5")
    print("=" * 100)
    print(f"  Full data      : {closes_all.index[0].date()} -> {closes_all.index[-1].date()}")
    print(f"  Holdout sealed : last {HOLDOUT_MONTHS} months "
          f"({cutoff.date()} -> {closes_all.index[-1].date()}) — NOT used below")
    print(f"  Development    : {closes.index[0].date()} -> {closes.index[-1].date()} "
          f"({(closes.index[-1]-closes.index[0]).days/365.25:.1f} years)")
    print(f"  Universe       : {closes.shape[1]} symbols")

    # Momentum needs a 12-month lookback plus the skip month before it can rank
    # anything, so the first tradable date is well after the data starts.
    warmup = closes.index[0] + pd.DateOffset(months=14)
    first_test = max(warmup, closes.index[0] + pd.DateOffset(
        months=int(args.min_train_years * 12)))

    folds = []
    t = first_test
    while t < closes.index[-1]:
        t_end = t + pd.DateOffset(years=args.test_years)
        if t_end > closes.index[-1]:
            t_end = closes.index[-1]
        if (t_end - t).days < 200:      # don't report a stub window
            break
        folds.append((closes.index[0], t, t_end))
        t = t_end
    print(f"  Folds          : {len(folds)} x {args.test_years:g}-year "
          f"out-of-sample windows\n")

    # ---------------------------------------------------------------- Test A
    print("=" * 100)
    print("  A. STABILITY — the pre-registered baseline, never re-fitted")
    print("=" * 100)
    print(f"  {'window':<26}{'momentum%':>12}{'benchmark%':>13}{'edge%':>10}"
          f"{'Sharpe':>9}{'maxDD%':>9}")

    rows_a = []
    base_cfg, base_rebal = MomentumConfig(), "ME"
    for _, t0, t1 in folds:
        st = run_window(closes, volumes, base_cfg, base_rebal, t0, t1)
        bs = benchmark_window(closes, volumes, t0, t1)
        if st is None or not bs:
            continue
        edge = st["cagr_pct"] - bs["cagr_pct"]
        rows_a.append({"window": f"{t0.date()} -> {t1.date()}",
                       "momentum_pct": st["cagr_pct"],
                       "benchmark_pct": bs["cagr_pct"],
                       "edge_pct": edge,
                       "sharpe": st["sharpe"],
                       "max_dd_pct": st["max_dd_pct"]})
        mark = "   <- lost" if edge < 0 else ""
        print(f"  {rows_a[-1]['window']:<26}{st['cagr_pct']:>12.1f}"
              f"{bs['cagr_pct']:>13.1f}{edge:>+10.1f}{st['sharpe']:>9.2f}"
              f"{st['max_dd_pct']:>9.1f}{mark}")

    a = pd.DataFrame(rows_a)
    edges = a["edge_pct"]
    n_win = int((edges > 0).sum())
    # t-test on per-window edges: is the mean edge distinguishable from zero
    # across independent windows, rather than driven by one of them?
    se = edges.std(ddof=1) / np.sqrt(len(edges)) if len(edges) > 1 else np.nan
    tstat = edges.mean() / se if se and se > 0 else np.nan
    print(f"\n  Windows won        : {n_win}/{len(a)}")
    print(f"  Mean edge          : {edges.mean():+.2f}%/yr")
    print(f"  Median edge        : {edges.median():+.2f}%/yr")
    print(f"  t-stat on windows  : {tstat:.2f}  "
          f"({'distinguishable from zero' if abs(tstat) > 2 else 'NOT distinguishable from zero'})")
    print(f"  Worst window       : {edges.min():+.2f}%/yr")
    if len(a) > 1:
        without_best = edges.drop(edges.idxmax())
        print(f"  Mean without the single best window: {without_best.mean():+.2f}%/yr "
              f"({'still positive' if without_best.mean() > 0 else 'turns negative'})")

    # ---------------------------------------------------------------- Test B
    print("\n" + "=" * 100)
    print("  B. SELECTION — does picking the best in-sample variant help out-of-sample?")
    print("=" * 100)
    print("  Each fold: rank all 11 candidates on data up to the fold start, take the")
    print("  best by Sharpe, then apply THAT choice to the unseen window.\n")
    print(f"  {'window':<26}{'selected variant':<30}{'sel%':>8}{'base%':>8}"
          f"{'bench%':>8}{'sel-base':>10}")

    rows_b = []
    for train_start, t0, t1 in folds:
        scored = []
        for name, cfg, rebal in CANDIDATES:
            st = run_window(closes, volumes, cfg, rebal, train_start, t0)
            if st is not None:
                scored.append((st["sharpe"], name, cfg, rebal))
        if not scored:
            continue
        scored.sort(key=lambda x: -x[0])
        _, sel_name, sel_cfg, sel_rebal = scored[0]

        sel = run_window(closes, volumes, sel_cfg, sel_rebal, t0, t1)
        base = run_window(closes, volumes, base_cfg, base_rebal, t0, t1)
        bs = benchmark_window(closes, volumes, t0, t1)
        if sel is None or base is None or not bs:
            continue
        rows_b.append({"window": f"{t0.date()} -> {t1.date()}",
                       "selected": sel_name,
                       "selected_pct": sel["cagr_pct"],
                       "baseline_pct": base["cagr_pct"],
                       "benchmark_pct": bs["cagr_pct"],
                       "sel_minus_base": sel["cagr_pct"] - base["cagr_pct"]})
        r = rows_b[-1]
        print(f"  {r['window']:<26}{sel_name[:29]:<30}{r['selected_pct']:>8.1f}"
              f"{r['baseline_pct']:>8.1f}{r['benchmark_pct']:>8.1f}"
              f"{r['sel_minus_base']:>+10.1f}")

    b = pd.DataFrame(rows_b)
    if len(b):
        d = b["sel_minus_base"]
        print(f"\n  Selection beat the fixed baseline in {int((d > 0).sum())}/{len(b)} windows")
        print(f"  Mean(selected - baseline) : {d.mean():+.2f}%/yr")
        print(f"  Distinct variants chosen  : {b['selected'].nunique()} "
              f"({', '.join(sorted(b['selected'].unique())[:3])}"
              f"{'...' if b['selected'].nunique() > 3 else ''})")
        if d.mean() <= 0:
            print("\n  READING: chasing the best in-sample variant did NOT pay out-of-sample.")
            print("  The 14-variant sweep was fitting noise, and the pre-registered")
            print("  baseline is the honest configuration to trade. This is the useful")
            print("  outcome — it removes the temptation to trade the sweep winner.")
        else:
            print("\n  READING: selection added value out-of-sample. Treat with care —")
            print("  it is still only a handful of windows, and the variants are")
            print("  correlated with each other.")

    # ---------------------------------------------------------------- verdict
    print("\n" + "=" * 100)
    print("  CRITERION 5 — survives walk-forward without re-fitting")
    print("=" * 100)
    majority = n_win >= (len(a) + 1) // 2
    positive = edges.mean() > 0
    robust = len(a) > 1 and edges.drop(edges.idxmax()).mean() > 0
    ok = majority and positive and robust
    print(f"  Baseline positive in a majority of windows : {n_win}/{len(a)}  "
          f"[{'PASS' if majority else 'FAIL'}]")
    print(f"  Mean out-of-sample edge > 0                : {edges.mean():+.2f}%/yr  "
          f"[{'PASS' if positive else 'FAIL'}]")
    print(f"  Not carried by one window                  : "
          f"[{'PASS' if robust else 'FAIL'}]")
    print(f"\n  CRITERION 5: {'PASS' if ok else 'FAIL'}")
    print("\n  Note: these windows are out-of-sample in TIME but drawn from the same")
    print("  205-symbol universe selected by TODAY's index membership. Walk-forward")
    print("  cannot remove survivorship bias — only forward paper trading can.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    a.to_csv(RESULTS_DIR / "walk_forward_stability.csv", index=False)
    if len(b):
        b.to_csv(RESULTS_DIR / "walk_forward_selection.csv", index=False)
    print(f"\nSaved: {RESULTS_DIR / 'walk_forward_stability.csv'}")


if __name__ == "__main__":
    main()
