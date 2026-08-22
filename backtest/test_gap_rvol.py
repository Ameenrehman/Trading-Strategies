"""
Test the Dynamic Gap + RVOL Momentum strategy.

The experiment phase-1-backtesting.md section 4 calls make-or-break: does the
monotonic "edge rises with gap size" relationship survive a corrected
implementation (stop-entry fills, risk-based sizing, true RR, trailing exits)?

Reports gross bps/trade, the *realised* cost per trade at the sizes actually
traded, and net bps/trade with a t-stat. Total return is printed only as a
secondary figure - it is size-dependent and easy to misread (section 1).

Every variant tested here counts against the multiple-comparisons budget, so
the variant count is printed at the end.
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
RESULTS_DIR = Path(__file__).parent / "results"
LEVERAGE = 5.0
MARGIN = 1.0 / LEVERAGE


def load_all():
    out = {}
    for csv in sorted(DATA_DIR.glob("*_5min.csv")):
        df = pd.read_csv(csv, parse_dates=["datetime"]).set_index("datetime").sort_index()
        df.columns = [c.capitalize() for c in df.columns]
        out[csv.stem.replace("_5min", "")] = df
    return out


def per_trade_bps(trades):
    return (trades["PnL"] / (trades["EntryPrice"] * trades["Size"].abs())) * 1e4


def evaluate(data_by_symbol, label, **params):
    """Run one variant across all symbols; return pooled gross/net stats."""
    gross, net, notionals, returns = [], [], [], []

    for sym, data in data_by_symbol.items():
        bt_g = Backtest(data, GapRVOLMomentum, cash=100_000, commission=0.0,
                        spread=0.0, margin=MARGIN, trade_on_close=True,
                        exclusive_orders=False, finalize_trades=True)
        tg = bt_g.run(**params)["_trades"]

        bt_n = Backtest(data, GapRVOLMomentum, cash=100_000,
                        commission=angel_intraday_commission,
                        spread=SLIPPAGE_PER_LEG, margin=MARGIN,
                        trade_on_close=True, exclusive_orders=False,
                        finalize_trades=True)
        stn = bt_n.run(**params)
        tn = stn["_trades"]

        if len(tg):
            gross.append(per_trade_bps(tg))
            notionals.append(tg["EntryPrice"] * tg["Size"].abs())
        if len(tn):
            net.append(per_trade_bps(tn))
        returns.append(stn.get("Return [%]", np.nan))

    if not gross:
        return None

    g = pd.concat(gross)
    n = pd.concat(net) if net else pd.Series(dtype=float)
    notional = pd.concat(notionals)

    gm = g.mean()
    gse = g.std(ddof=1) / np.sqrt(len(g))
    nm = n.mean() if len(n) else np.nan
    nse = n.std(ddof=1) / np.sqrt(len(n)) if len(n) > 1 else np.nan

    return {
        "variant": label,
        "trades": len(g),
        "per_stock_yr": len(g) / 5 / 2,
        "gross_bps": gm,
        "gross_t": gm / gse,
        "cost_bps": gm - nm,
        "net_bps": nm,
        "net_t": nm / nse if nse and nse > 0 else np.nan,
        "med_notional": notional.median(),
        "avg_return_pct": np.nanmean(returns),
    }


def main():
    data = load_all()
    rows = []
    variants = 0

    print("Sweeping gap threshold with an ATR chandelier trailing exit...")
    for mg in [0.3, 0.5, 0.75, 1.0, 1.5]:
        r = evaluate(data, f"trail2.0 gap>={mg}%", min_gap_pct=mg,
                     trail_atr_mult=2.0, rvol_mult=0.0)
        variants += 1
        if r:
            rows.append(r)

    print("Sweeping gap threshold with a fixed 2:1 target (no trailing)...")
    for mg in [0.5, 1.0]:
        r = evaluate(data, f"fixed2:1 gap>={mg}%", min_gap_pct=mg,
                     trail_atr_mult=0.0, rr_ratio=2.0, rvol_mult=0.0)
        variants += 1
        if r:
            rows.append(r)

    print("Testing the RVOL and trend filters at the 1.0% threshold...")
    for label, kw in [
        ("trail2.0 gap>=1.0% +rvol1.5", dict(min_gap_pct=1.0, trail_atr_mult=2.0, rvol_mult=1.5)),
        ("trail2.0 gap>=1.0% +trend", dict(min_gap_pct=1.0, trail_atr_mult=2.0,
                                           rvol_mult=0.0, use_trend_filter=True)),
        ("trail3.0 gap>=1.0%", dict(min_gap_pct=1.0, trail_atr_mult=3.0, rvol_mult=0.0)),
    ]:
        r = evaluate(data, label, **kw)
        variants += 1
        if r:
            rows.append(r)

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)

    print("\n" + "=" * 118)
    print("  DYNAMIC GAP + RVOL MOMENTUM - pooled across 5 stocks, 2 years")
    print("=" * 118)
    show = df[["variant", "trades", "per_stock_yr", "gross_bps", "gross_t",
               "cost_bps", "net_bps", "net_t", "med_notional", "avg_return_pct"]]
    print(show.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print("\nNotes:")
    print(f"  - cost_bps is the REALISED cost per trade at the sizes actually traded,")
    print(f"    not the flat 20.6 bps assumption (which is for a Rs.50,000 position).")
    print(f"  - Bonferroni threshold for {variants} variants at alpha=0.05: |t| > "
          f"{abs(round(float(np.abs(_z_bonferroni(variants))), 2))}")
    print(f"  - Variants tested in this run: {variants}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "gap_rvol_summary.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")


def _z_bonferroni(k, alpha=0.05):
    """Two-sided critical z for k comparisons (normal approximation)."""
    from math import sqrt
    try:
        from statistics import NormalDist
        return NormalDist().inv_cdf(1 - alpha / (2 * k))
    except Exception:
        return 3.0


if __name__ == "__main__":
    main()
