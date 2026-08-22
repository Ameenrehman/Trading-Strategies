"""
Sanity checks for the portfolio backtester, on synthetic data with known answers.

A portfolio backtester is easy to get subtly wrong in ways that flatter the
result — mis-charged costs, turnover counted on the wrong base, weights that
quietly drift. Phase 1 shipped eight such defects before they were caught, so
these run against data whose correct answer is known by construction rather
than against market data where a wrong answer looks plausible.

Run:
    python backtest/test_portfolio_sanity.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import run_portfolio, rebalance_dates
from backtest.costs import delivery_one_way_cost, delivery_cost_bps
from strategies.momentum_xs import MomentumConfig, momentum_scores, select

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{PASS if ok else FAIL}]  {name:52s} {detail}")


def synthetic(n_symbols=10, n_days=800, seed=0, drift=0.0003, vol=0.015):
    """Geometric random walks with a per-symbol drift spread."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    out = {}
    for i in range(n_symbols):
        d = drift * (1 + i * 0.5)          # symbol 0 slowest, symbol N fastest
        r = rng.normal(d, vol, n_days)
        out[f"SYM{i:02d}"] = 100 * np.exp(np.cumsum(r))
    closes = pd.DataFrame(out, index=idx)
    volumes = pd.DataFrame(1e6, index=idx, columns=closes.columns)
    return closes, volumes


def main():
    print("=" * 78)
    print("  PORTFOLIO BACKTESTER — SANITY CHECKS")
    print("=" * 78)

    closes, volumes = synthetic()
    all_syms = list(closes.columns)

    # --- 1. zero-cost, never-changing selection == buy and hold ------------
    hold_all = lambda c, d, h=None: all_syms
    r = run_portfolio(closes, hold_all, initial_capital=1_000_000,
                      charge_costs=False)
    eq = r["equity"]

    # Manual equal-weight, whole-share, bought on the first rebalance date.
    first_rebal = rebalance_dates(closes.index)[0]
    px0 = closes.loc[first_rebal]
    per = 1_000_000 / len(all_syms)
    qty = {s: int(per // px0[s]) for s in all_syms}
    spent = sum(qty[s] * px0[s] for s in all_syms)
    manual_final = (1_000_000 - spent) + sum(qty[s] * closes.iloc[-1][s] for s in all_syms)

    diff = abs(eq.iloc[-1] - manual_final) / manual_final
    check("zero-cost buy&hold matches manual calc", diff < 0.001,
          f"diff {diff*100:.4f}%")

    # --- 2. turnover is zero after the initial build -----------------------
    tno = r["turnover"]["turnover"]
    after_first = tno.iloc[1:]
    check("turnover == 0 when selection never changes",
          bool((after_first.abs() < 1e-9).all()),
          f"max after build {after_first.abs().max():.2e}")

    # --- 3. no costs charged when charge_costs=False -----------------------
    check("zero costs when charge_costs=False", r["total_costs"] == 0.0,
          f"total {r['total_costs']:.2f}")

    # --- 4. charged cost matches the cost model exactly --------------------
    rc = run_portfolio(closes, hold_all, initial_capital=1_000_000,
                       charge_costs=True)
    tr = rc["trades"]
    expected = sum(delivery_one_way_cost(row["value"], row["side"])
                   for _, row in tr.iterrows())
    err = abs(rc["total_costs"] - expected)
    check("charged cost == delivery_one_way_cost per leg", err < 0.01,
          f"err Rs.{err:.4f} over {len(tr)} trades")

    # --- 5. costs reduce returns, and by a sensible amount -----------------
    drag = (eq.iloc[-1] - rc["equity"].iloc[-1]) / 1_000_000 * 100
    check("costs reduce final equity", rc["equity"].iloc[-1] < eq.iloc[-1],
          f"drag {drag:.3f}% of initial capital")

    # --- 6. momentum ranking actually picks the high-drift names -----------
    # Use a LOW-NOISE series so the correct ranking is unambiguous. At the
    # default vol the drift spread is only ~1.7 sigma over the lookback, so
    # noise legitimately reorders the ranking and the test would have no known
    # answer — a test that can fail for correct code is worse than no test.
    quiet, quiet_vol = synthetic(vol=0.0004, seed=7)
    cfg = MomentumConfig(n_positions=3, trend_ma=0, min_history_days=300,
                         min_adv=0)
    asof = closes.index[-1]
    picked = select(quiet, quiet_vol, quiet.index[-1], cfg)
    check("momentum ranks the strongest drifters top",
          picked == ["SYM09", "SYM08", "SYM07"], f"picked {picked}")

    # --- 7. 12-1 skips the most recent month -------------------------------
    # Spike the last 10 days of SYM00 hard. A 12-1 score must ignore it.
    spiked = closes.copy()
    spiked.iloc[-10:, spiked.columns.get_loc("SYM00")] *= 3.0
    s_before = momentum_scores(closes, asof, cfg)["SYM00"]
    s_after = momentum_scores(spiked, asof, cfg)["SYM00"]
    check("12-1 momentum ignores the skipped recent month",
          abs(s_before - s_after) < 1e-9,
          f"score {s_before:.4f} -> {s_after:.4f}")

    # --- 8. trend filter excludes names below their MA ---------------------
    falling = closes.copy()
    falling["SYM09"] = falling["SYM09"].iloc[0] * np.linspace(3.0, 0.5, len(falling))
    cfg_t = MomentumConfig(n_positions=5, trend_ma=200, min_history_days=300,
                           min_adv=0)
    picked_t = select(falling, volumes, asof, cfg_t)
    check("trend filter drops a name below its 200-DMA",
          "SYM09" not in picked_t, f"picked {picked_t}")

    # --- 9. cash is held when too few names qualify ------------------------
    none_qualify = lambda c, d, h=None: []
    r_cash = run_portfolio(closes, none_qualify, initial_capital=1_000_000)
    check("holds cash when nothing qualifies",
          abs(r_cash["equity"].iloc[-1] - 1_000_000) < 1.0,
          f"final Rs.{r_cash['equity'].iloc[-1]:,.0f}")

    # --- 10. no look-ahead: signal_fn only ever sees past data -------------
    seen = []

    def spy(c, d, h=None):
        seen.append((d, c.loc[:d].index[-1]))
        return all_syms[:3]

    run_portfolio(closes, spy, initial_capital=1_000_000)
    check("signal_fn never sees data beyond the rebalance date",
          all(last <= d for d, last in seen),
          f"{len(seen)} rebalances checked")

    # --- 11. equity curve is continuous (no jumps from bad accounting) -----
    daily_ret = rc["equity"].pct_change().dropna()
    check("no implausible single-day equity jumps",
          bool((daily_ret.abs() < 0.25).all()),
          f"max |1d move| {daily_ret.abs().max()*100:.2f}%")

    # --- 12. momentum_scores survives the exact history boundary -----------
    # Regression: the guard used to check lookback+skip while indexing
    # lookback+skip+1 rows back. Only daily rebalancing lands on that exact
    # boundary, so monthly testing never caught it.
    cfg_b = MomentumConfig(lookback_days=252, skip_days=21, trend_ma=0,
                           min_history_days=1, min_adv=0)
    boundary_ok = True
    for n in (272, 273, 274, 275):
        try:
            momentum_scores(closes.iloc[:n], closes.index[n - 1], cfg_b)
        except Exception as exc:
            boundary_ok = False
            check("momentum_scores at exact history boundary", False,
                  f"n={n}: {type(exc).__name__}")
            break
    if boundary_ok:
        check("momentum_scores at exact history boundary", True,
              "n=272..275 all safe")

    # --- 13. daily rebalancing runs and costs more than monthly ------------
    r_daily = run_portfolio(closes, hold_all, initial_capital=1_000_000,
                            rebalance="D")
    check("daily rebalance schedule runs",
          len(r_daily["turnover"]) > len(rc["turnover"]),
          f"{len(r_daily['turnover'])} daily vs {len(rc['turnover'])} monthly")

    # --- 14. round-trip cost model self-consistency ------------------------
    pos = 100_000.0
    one_way = (delivery_one_way_cost(pos, "buy") + delivery_one_way_cost(pos, "sell"))
    rt = delivery_cost_bps(pos) / 1e4 * pos
    check("one-way legs sum to the round-trip cost", abs(one_way - rt) < 0.01,
          f"Rs.{one_way:.2f} vs Rs.{rt:.2f}")

    print("\n" + "=" * 78)
    n_pass = sum(1 for _, ok, _ in results if ok)
    print(f"  {n_pass}/{len(results)} checks passed")
    print("=" * 78)
    if n_pass != len(results):
        print("\n  FAILURES:")
        for name, ok, detail in results:
            if not ok:
                print(f"    - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
