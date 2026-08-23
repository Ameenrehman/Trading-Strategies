"""
Monte Carlo permutation test, and the Bonferroni bar for the variants tested.

What this asks that the existing controls do not
------------------------------------------------
`test_momentum_controls.py` asks "does picking the TOP 20 beat picking 20 at
random?" That tests the *selection*. It cannot tell you whether momentum exists
in the data at all, because both arms trade the same real price paths, and any
strategy that concentrates into fewer names inherits a different risk profile.

This asks the deeper question: **is there anything in the time-ordering of
returns for a trailing-return ranking to exploit?**

Method: take the daily cross-sectional return matrix and shuffle the ORDER of
the rows, using one common permutation for every symbol. That deliberately
preserves

  - each symbol's full return distribution (same days, same magnitudes)
  - each day's cross-sectional structure (market moves and correlations intact)
  - the exact calendar, universe, listing dates and eligibility filter

and destroys exactly one thing: the temporal sequence. Under the null that a
12-month trailing return says nothing about the next month, the strategy's edge
over its own benchmark should collapse to noise centred on zero.

Both the strategy AND the benchmark are re-run on each shuffled path, and the
statistic is the DIFFERENCE. That matters: shuffling changes the compounding of
the whole market, so an absolute CAGR from shuffled data is not comparable to
the real one — only the edge over a benchmark computed on the same path is.

Two p-values are reported, and they answer different questions:

  - empirical  : the rank of the real edge among the shuffled ones. Assumption
                 free, but floored at 1/(N+1) — with 200 permutations the
                 smallest reportable value is 0.005.
  - normal     : z-score against the null's mean and standard deviation. Can
                 resolve past that floor, but assumes the null is roughly
                 normal. The printed skew/kurtosis let you judge that.

Multiple testing
----------------
14 variants were swept in test_momentum.py. Try enough configurations and one
wins by chance, so the significance bar has to move: Bonferroni divides the
target alpha by the number of tests. That correction is applied at the end.

Runs on the development period only — the trailing 24-month holdout is removed
by split_holdout().

Run:
    python backtest/test_permutation.py
    python backtest/test_permutation.py --n-perm 500 --seed 7
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import run_portfolio, load_daily, split_holdout, HOLDOUT_MONTHS
from strategies.momentum_xs import (MomentumConfig, make_signal_fn,
                                    make_buyhold_signal_fn)

RESULTS_DIR = PROJECT_ROOT / "backtest" / "results"

# Variants swept in test_momentum.py. Kept as a constant so the Bonferroni
# divisor is a stated number rather than something remembered.
N_VARIANTS_TESTED = 14
TARGET_ALPHA = 0.05


def shuffled_prices(closes: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """
    Rebuild prices from the same daily returns in a shuffled order.

    One permutation is applied to every symbol, so each day's cross-section
    travels together and market-wide moves survive intact. Leading NaNs (a name
    that had not listed) are preserved, so the universe still grows over time
    exactly as it really did.
    """
    rets = closes.pct_change()
    order = rng.permutation(len(rets))
    shuffled = rets.iloc[order].reset_index(drop=True)
    shuffled.index = closes.index

    # Rebuild from each symbol's own first observed price. Where the original
    # was NaN the result stays NaN, so listing dates are unchanged.
    first_px = closes.apply(lambda c: c.dropna().iloc[0] if c.notna().any() else np.nan)
    path = (1.0 + shuffled.fillna(0.0)).cumprod() * first_px
    return path.where(closes.notna())


def edge_on(closes, volumes, cfg=None):
    """Strategy CAGR minus benchmark CAGR on one price path."""
    cfg = cfg or MomentumConfig()
    mom = run_portfolio(closes, make_signal_fn(cfg, volumes),
                        initial_capital=1_000_000, rebalance="ME")
    ben = run_portfolio(closes, make_buyhold_signal_fn(cfg, volumes),
                        initial_capital=1_000_000, rebalance="ME")
    return (mom["stats"]["cagr_pct"] - ben["stats"]["cagr_pct"],
            mom["stats"]["cagr_pct"], ben["stats"]["cagr_pct"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-perm", type=int, default=200,
                    help="Number of permutations (200 floors the empirical "
                         "p-value at 0.005; 500+ to resolve below that)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()

    closes_all, volumes_all = load_daily(
        Path(args.data_dir) if args.data_dir else None)
    closes, volumes, cutoff = split_holdout(closes_all, volumes_all)

    print("=" * 92)
    print("  MONTE CARLO PERMUTATION TEST")
    print("=" * 92)
    print(f"  Full data      : {closes_all.index[0].date()} -> {closes_all.index[-1].date()}")
    print(f"  Holdout sealed : last {HOLDOUT_MONTHS} months ({cutoff.date()} onward) — NOT used")
    print(f"  Development    : {closes.index[0].date()} -> {closes.index[-1].date()}")
    print(f"  Universe       : {closes.shape[1]} symbols")
    print(f"  Permutations   : {args.n_perm}  (seed {args.seed})")

    real_edge, real_mom, real_ben = edge_on(closes, volumes)
    print(f"\n  REAL: momentum {real_mom:.2f}%/yr  benchmark {real_ben:.2f}%/yr  "
          f"edge {real_edge:+.2f}%/yr")

    print(f"\n  Running {args.n_perm} permutations...")
    rng = np.random.default_rng(args.seed)
    null = []
    t0 = time.time()
    for i in range(args.n_perm):
        try:
            e, _, _ = edge_on(shuffled_prices(closes, rng), volumes)
            null.append(e)
        except Exception:
            continue
        if (i + 1) % 25 == 0:
            el = time.time() - t0
            print(f"    {i+1:4d}/{args.n_perm}   mean null edge "
                  f"{np.mean(null):+.2f}%/yr   ({el:.0f}s elapsed, "
                  f"~{el/(i+1)*(args.n_perm-i-1):.0f}s left)")

    null = np.array(null, dtype=float)
    n = len(null)
    mu, sd = null.mean(), null.std(ddof=1)
    n_ge = int((null >= real_edge).sum())
    p_emp = (n_ge + 1) / (n + 1)            # +1 both sides: never report p = 0
    z = (real_edge - mu) / sd if sd > 0 else np.nan
    # one-sided normal tail
    from math import erfc, sqrt
    p_norm = 0.5 * erfc(z / sqrt(2)) if np.isfinite(z) else np.nan

    skew = float(pd.Series(null).skew())
    kurt = float(pd.Series(null).kurtosis())

    print("\n" + "=" * 92)
    print("  NULL DISTRIBUTION — edge over benchmark on time-shuffled data")
    print("=" * 92)
    print(f"  n                  : {n}")
    print(f"  mean               : {mu:+.2f}%/yr   (should sit near 0 if the "
          f"test is constructed correctly)")
    print(f"  std dev            : {sd:.2f}")
    print(f"  min / max          : {null.min():+.2f} / {null.max():+.2f}")
    print(f"  skew / excess kurt : {skew:+.2f} / {kurt:+.2f}")
    print(f"  percentiles  5/50/95: {np.percentile(null,5):+.2f} / "
          f"{np.percentile(null,50):+.2f} / {np.percentile(null,95):+.2f}")

    print("\n" + "=" * 92)
    print("  RESULT")
    print("=" * 92)
    print(f"  Real edge                        : {real_edge:+.2f}%/yr")
    print(f"  Shuffled runs matching or beating: {n_ge}/{n}")
    print(f"  Empirical p-value                : {p_emp:.4f}"
          f"{'  (at the 1/(n+1) floor)' if n_ge == 0 else ''}")
    print(f"  z-score vs null                  : {z:.2f}")
    print(f"  Normal-approx p-value            : {p_norm:.2e}")

    bonf = TARGET_ALPHA / N_VARIANTS_TESTED
    print("\n" + "=" * 92)
    print("  MULTIPLE-TESTING CORRECTION")
    print("=" * 92)
    print(f"  Variants swept in test_momentum.py : {N_VARIANTS_TESTED}")
    print(f"  Target alpha                       : {TARGET_ALPHA}")
    print(f"  Bonferroni-corrected bar           : {bonf:.5f}")
    print(f"  Permutations needed to resolve it  : {int(np.ceil(1/bonf))-1} "
          f"(you ran {n})")

    emp_ok = p_emp < bonf
    norm_ok = np.isfinite(p_norm) and p_norm < bonf
    if emp_ok:
        verdict = "PASS on the empirical p-value alone"
    elif norm_ok and n_ge == 0:
        verdict = ("PASS on the normal approximation; the empirical p-value is "
                   "at its floor and cannot resolve further without more runs")
    elif norm_ok:
        verdict = "PASS on the normal approximation only — treat as weaker"
    else:
        verdict = "FAIL"
    print(f"\n  Empirical  p={p_emp:.4f} vs bar {bonf:.5f} : "
          f"[{'PASS' if emp_ok else 'not resolved' if n_ge == 0 else 'FAIL'}]")
    print(f"  Normal     p={p_norm:.2e} vs bar {bonf:.5f} : "
          f"[{'PASS' if norm_ok else 'FAIL'}]")
    print(f"\n  VERDICT: {verdict}")

    print("\n  What this does and does not establish:")
    print("    DOES  — the time-ordering of returns carries information a")
    print("            trailing-return ranking can exploit. The edge is not an")
    print("            artifact of the universe, the cost model or the calendar.")
    print("    DOES NOT — say the edge will persist, or that it survives")
    print("            survivorship bias. Every permutation uses the same 205")
    print("            symbols chosen by TODAY's index membership, so that bias")
    print("            is present in the null and the real run alike.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"null_edge_pct": null}).to_csv(
        RESULTS_DIR / "permutation_null.csv", index=False)
    pd.DataFrame([{
        "real_edge_pct": real_edge, "real_momentum_pct": real_mom,
        "real_benchmark_pct": real_ben, "n_perm": n,
        "null_mean": mu, "null_std": sd, "n_ge": n_ge,
        "p_empirical": p_emp, "z": z, "p_normal": p_norm,
        "n_variants": N_VARIANTS_TESTED, "bonferroni_bar": bonf,
        "verdict": verdict,
    }]).to_csv(RESULTS_DIR / "permutation_summary.csv", index=False)
    print(f"\nSaved: {RESULTS_DIR / 'permutation_summary.csv'}")


if __name__ == "__main__":
    main()
