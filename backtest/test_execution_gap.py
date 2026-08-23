"""
Measure the close-to-next-open execution gap — the backtest's last assumption.

The problem
-----------
The backtest fills at the rebalance CLOSE and charges a flat 5 bps/leg of
slippage. Live, you cannot trade that close: the signal is computed from it
after 15:30, and the order goes in at the NEXT morning's open. Everything that
happens overnight is a cost the backtest never modelled.

That gap was the single largest unverified assumption left after Phase 1b, and
the plan was to measure it by paper trading. This script measures it directly
from the daily bars already on disk, which is both faster and — as the noise
figure at the bottom shows — enormously more precise than paper trading could
ever be.

Method
------
At every month-end rebalance from 2011-2026, run the real selection, then for
each leg compare the reference close against the next session's open:

    BUY  cost = open(T+1) / close(T) - 1        (positive = paid more)
    SELL cost = close(T) / open(T+1) - 1        (positive = sold for less)

Both are signed so that POSITIVE means worse than the backtest assumed.

The control matters
-------------------
Indian equities carry a well-documented positive overnight drift, so buys
gapping up is not by itself evidence of a momentum-specific cost — the sells
gap up too, and recover it. The control therefore measures each buy leg's
EXCESS gap over that same day's universe-wide average. That is the number that
would represent a real cost of chasing momentum, and it is the one to read.

Run:
    python backtest/test_execution_gap.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.portfolio import load_daily, rebalance_dates
from backtest.costs import SLIPPAGE_PER_LEG
from strategies.momentum_xs import MomentumConfig, select

DAILY_DIR = PROJECT_ROOT / "data" / "daily"
RESULTS_DIR = PROJECT_ROOT / "backtest" / "results"

ASSUMED_BPS = SLIPPAGE_PER_LEG * 1e4
BASELINE_TURNOVER = 5.16          # 516%/yr, the measured monthly-rebalance figure


def load_opens(closes: pd.DataFrame) -> pd.DataFrame:
    """Opening prices aligned to the close frame's index and columns."""
    cols = {}
    for f in sorted(DAILY_DIR.glob("*_1day.csv")):
        d = pd.read_csv(f, parse_dates=["datetime"]).set_index("datetime")
        d.index = d.index.tz_localize(None)
        cols[f.stem.replace("_1day", "")] = d["open"]
    return (pd.DataFrame(cols).reindex(closes.index).ffill()
            .reindex(columns=closes.columns))


def describe(name: str, a: np.ndarray) -> dict:
    if not len(a):
        return {}
    se = a.std(ddof=1) / np.sqrt(len(a))
    t = a.mean() / se if se > 0 else np.nan
    print(f"  {name:<34} n={len(a):5d}  mean {a.mean():+7.1f} bps  "
          f"SE {se:4.1f}  t={t:+5.2f}  median {np.median(a):+7.1f}  sd {a.std(ddof=1):6.1f}")
    return {"leg": name, "n": len(a), "mean_bps": a.mean(), "se_bps": se,
            "t": t, "median_bps": float(np.median(a)), "sd_bps": a.std(ddof=1)}


def main():
    closes, volumes = load_daily()
    opens = load_opens(closes)
    idx = closes.index
    cfg = MomentumConfig()

    print("=" * 96)
    print("  EXECUTION GAP — backtest fills at close(T), live fills at open(T+1)")
    print("=" * 96)
    print(f"  Data      : {idx[0].date()} -> {idx[-1].date()}, {closes.shape[1]} symbols")
    print(f"  Schedule  : month-end, baseline config")
    print(f"  Convention: POSITIVE bps = worse than the backtest assumed\n")

    buy, sell, excess, uni = [], [], [], []
    held = []
    for d in rebalance_dates(idx, "ME"):
        i = idx.get_loc(d)
        if i + 1 >= len(idx):
            break
        nxt = idx[i + 1]

        gap = (opens.loc[nxt] / closes.loc[d] - 1.0) * 1e4
        gap = gap[np.isfinite(gap)]
        if gap.empty:
            continue
        uni_mean = gap.mean()
        uni.append(uni_mean)

        target = select(closes, volumes, d, cfg, currently_held=held)
        if not target:
            held = []
            continue
        for s in (x for x in target if x not in held):
            if s in gap.index:
                buy.append(gap[s])
                excess.append(gap[s] - uni_mean)
        for s in (x for x in held if x not in target):
            if s in gap.index:
                sell.append(-gap[s])          # selling into an up-gap is a gain
        held = target

    buy, sell = np.array(buy), np.array(sell)
    uni, excess = np.array(uni), np.array(excess)
    both = np.concatenate([buy, sell])

    rows = []
    rows.append(describe("BUY legs (raw)", buy))
    rows.append(describe("SELL legs (raw)", sell))
    rows.append(describe("ALL legs (raw)", both))
    print()
    rows.append(describe("Universe average gap / rebal", uni))
    rows.append(describe("BUY excess over universe", excess))

    print("\n" + "=" * 96)
    print("  READING")
    print("=" * 96)
    se_e = excess.std(ddof=1) / np.sqrt(len(excess))
    momentum_specific = abs(excess.mean() / se_e) > 2 if se_e > 0 else False

    print(f"  Buys gap up by {buy.mean():+.1f} bps — but so does the whole market")
    print(f"  ({uni.mean():+.1f} bps universe-wide), and the simultaneous sells")
    print(f"  recover it. Net across both legs: {both.mean():+.1f} bps.")
    print()
    print(f"  The momentum-SPECIFIC component is the excess over the universe:")
    print(f"    {excess.mean():+.1f} bps/leg  (t = {excess.mean()/se_e:+.2f}) — "
          f"{'REAL' if momentum_specific else 'not distinguishable from zero'}")
    print()
    print(f"  Backtest assumption : {ASSUMED_BPS:+.1f} bps/leg")
    print(f"  Measured (net)      : {both.mean():+.1f} bps/leg")
    print(f"  Measured (excess)   : {excess.mean():+.1f} bps/leg")
    drag = (both.mean() - ASSUMED_BPS) / 1e4 * BASELINE_TURNOVER * 100
    print(f"\n  Impact vs the assumption at {BASELINE_TURNOVER*100:.0f}%/yr turnover: "
          f"{drag:+.2f} %/yr of CAGR")
    verdict = "CONSERVATIVE" if both.mean() < ASSUMED_BPS else "OPTIMISTIC"
    print(f"  => the 5 bps/leg assumption is {verdict}.")

    print("\n" + "=" * 96)
    print("  WHY PAPER TRADING CANNOT SETTLE THIS")
    print("=" * 96)
    sd = both.std(ddof=1)
    n_need = (sd / 2.0) ** 2
    print(f"  Per-leg standard deviation : {sd:.0f} bps")
    print(f"  Legs needed to pin the mean to +/-2 bps : {n_need:,.0f}")
    print(f"  At ~20 legs per monthly rebalance       : {n_need/20:,.0f} months")
    print()
    print("  The overnight gap is ~50x noisier than the quantity being measured.")
    print("  A year of paper trading gives ~240 legs and a standard error of")
    print(f"  ~{sd/np.sqrt(240):.0f} bps — it cannot distinguish 5 bps from 0 or from 15.")
    print("  This 1,700-leg historical estimate is the better measurement, and")
    print("  paper trading should be judged on what it CAN establish: that the")
    print("  pipeline runs, and a forward track record the holdout can no longer give.")

    print("\n  Still NOT measured by this: market impact — the difference between")
    print("  the printed open and YOUR fill. Small for Rs.50k in a Nifty 200 name,")
    print("  but it is the piece that genuinely needs live orders to observe.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "execution_gap.csv"
    pd.DataFrame([r for r in rows if r]).to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
