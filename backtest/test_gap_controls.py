"""
Control tests for the Dynamic Gap + RVOL result.

The sweep in test_gap_rvol.py shows edge rising with gap size. There is an
obvious alternative explanation that has nothing to do with the strategy:
big-gap sessions are simply high-volatility sessions, and an ATR trailing stop
on a volatile day captures more range regardless of which way you enter. If
that is what's happening, the "edge" is a volatility artifact and will not
survive contact with a live market.

This is the randomized-entry benchmark from the phase-1 validation checklist,
made specific:

  Control A - random direction. Same qualifying days, same entry levels, same
  exits, but the trade direction is coin-flipped instead of following the gap.
  If the real strategy does not beat this, gap direction carries no
  information and the entry logic is adding nothing.

  Control B - inverted direction. Deliberately trade against the gap. A real
  continuation edge should show up as this being clearly worse than the real
  strategy, roughly mirrored around the control-A distribution.

Run:
    python backtest/test_gap_controls.py
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.gap_rvol_strategy import GapRVOLMomentum
from backtest.costs import angel_intraday_commission, SLIPPAGE_PER_LEG

warnings.filterwarnings("ignore")

DATA_DIR = PROJECT_ROOT / "data"
LEVERAGE = 5.0
MARGIN = 1.0 / LEVERAGE
N_SEEDS = 20

# The best in-sample variant from test_gap_rvol.py.
BASE = dict(min_gap_pct=1.0, trail_atr_mult=2.0, rvol_mult=1.5)


class RandomDirection(GapRVOLMomentum):
    """Same setups, coin-flipped direction. `seed` varies the coin."""
    seed = 0

    def init(self):
        super().init()
        # One deterministic flip per day, so a day's direction is stable
        # across the bars of that session.
        rng = np.random.default_rng(self.seed)
        n_days = int(self._day_id.max()) + 1
        self._flip = rng.choice([-1, 1], size=n_days)

    def _qualifies(self, i):
        d = super()._qualifies(i)
        if d == 0:
            return 0
        return int(self._flip[self._day_id[i]])


class InvertedDirection(GapRVOLMomentum):
    """Deliberately fade the gap instead of following it."""

    def _qualifies(self, i):
        return -super()._qualifies(i)


def load_all():
    out = {}
    for csv in sorted(DATA_DIR.glob("*_5min.csv")):
        df = pd.read_csv(csv, parse_dates=["datetime"]).set_index("datetime").sort_index()
        df.columns = [c.capitalize() for c in df.columns]
        out[csv.stem.replace("_5min", "")] = df
    return out


def per_trade_bps(trades):
    return (trades["PnL"] / (trades["EntryPrice"] * trades["Size"].abs())) * 1e4


def pooled(data_by_symbol, strategy, **params):
    """Pooled gross and net bps/trade for one configuration."""
    g, n = [], []
    for data in data_by_symbol.values():
        tg = Backtest(data, strategy, cash=100_000, commission=0.0, spread=0.0,
                      margin=MARGIN, trade_on_close=True, exclusive_orders=False,
                      finalize_trades=True).run(**params)["_trades"]
        tn = Backtest(data, strategy, cash=100_000,
                      commission=angel_intraday_commission, spread=SLIPPAGE_PER_LEG,
                      margin=MARGIN, trade_on_close=True, exclusive_orders=False,
                      finalize_trades=True).run(**params)["_trades"]
        if len(tg):
            g.append(per_trade_bps(tg))
        if len(tn):
            n.append(per_trade_bps(tn))
    if not g:
        return None
    G, N = pd.concat(g), (pd.concat(n) if n else pd.Series(dtype=float))
    return {"trades": len(G), "gross": G.mean(), "net": N.mean() if len(N) else np.nan}


def main():
    data = load_all()

    print("Running the real strategy...")
    real = pooled(data, GapRVOLMomentum, **BASE)

    print(f"Running control A (random direction) x {N_SEEDS} seeds...")
    ctrl = []
    for s in range(N_SEEDS):
        r = pooled(data, RandomDirection, seed=s, **BASE)
        if r:
            ctrl.append(r)

    print("Running control B (inverted direction)...")
    inv = pooled(data, InvertedDirection, **BASE)

    cg = np.array([c["gross"] for c in ctrl])
    cn = np.array([c["net"] for c in ctrl])

    print("\n" + "=" * 74)
    print("  CONTROL TEST - does gap DIRECTION carry information?")
    print("=" * 74)
    print(f"  Config: gap >= {BASE['min_gap_pct']}%, RVOL >= {BASE['rvol_mult']}, "
          f"ATR({BASE['trail_atr_mult']}) trailing stop")
    print()
    print(f"  {'':28s} {'trades':>7} {'gross bps':>10} {'net bps':>9}")
    print("  " + "-" * 60)
    print(f"  {'REAL (follow the gap)':28s} {real['trades']:>7} "
          f"{real['gross']:>10.2f} {real['net']:>9.2f}")
    print(f"  {'Control A random dir (mean)':28s} {ctrl[0]['trades']:>7} "
          f"{cg.mean():>10.2f} {cn.mean():>9.2f}")
    print(f"  {'  ... A best of ' + str(N_SEEDS) + ' seeds':28s} {'':>7} "
          f"{cg.max():>10.2f} {cn.max():>9.2f}")
    print(f"  {'  ... A worst of ' + str(N_SEEDS) + ' seeds':28s} {'':>7} "
          f"{cg.min():>10.2f} {cn.min():>9.2f}")
    print(f"  {'Control B inverted (fade)':28s} {inv['trades']:>7} "
          f"{inv['gross']:>10.2f} {inv['net']:>9.2f}")

    beat = int((cg >= real["gross"]).sum())
    pct = 100.0 * (1 - beat / len(cg))
    print()
    print(f"  Random-direction seeds matching or beating the real strategy: "
          f"{beat}/{len(cg)}")
    print(f"  => real strategy sits at roughly the {pct:.0f}th percentile of "
          f"random direction")
    print()
    if beat == 0 and real["gross"] > cg.max():
        print("  VERDICT: gap direction carries information - the real strategy")
        print("           beats every randomized-direction seed.")
    elif pct >= 95:
        print("  VERDICT: suggestive, but not decisive at this sample size.")
    else:
        print("  VERDICT: NOT SUPPORTED. The result is consistent with a")
        print("           volatility artifact rather than a directional edge.")
        print("           Trading volatile days with a trailing stop would do")
        print("           about as well regardless of which way you enter.")


if __name__ == "__main__":
    main()
