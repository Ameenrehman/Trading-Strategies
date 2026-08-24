"""
The shared price panel: every NSE daily CSV loaded into aligned OHLCV frames.

This is deliberately strategy-agnostic. It answers one question - "what did
these symbols do, point in time, with the data defects repaired" - and nothing
about what to trade.

Two repairs happen here rather than in each caller, because forgetting either
one silently fabricates signal:

  Corporate actions. The Angel One feed is UNADJUSTED, so a 1:10 split is a
  -90% day. Any strategy ranking on trailing returns will find it and load up
  on it. detect_price_steps() locates the discontinuities and history before
  the last one is discarded for that symbol.

  Calendar collapse. A handful of dates carry a near-empty cross-section -
  Muhurat sessions, exchange incidents, truncated feeds. A cross-sectional
  rank computed across 13 of 205 names is not a rank. Dropped by coverage
  rather than by a hardcoded list, so the rule still holds after a refresh.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.corporate_actions import detect_price_steps  # noqa: E402

MIN_CROSS_SECTION = 100

def load_daily_ohlc(data_dir: Path = None, repair_corporate_actions: bool = True,
                    min_cross_section: int = MIN_CROSS_SECTION,
                    report: bool = False):
    """
    Load every daily CSV into aligned open/high/low/close/volume frames.

    Returns a dict of five DataFrames sharing one DatetimeIndex, one column per
    symbol. Gaps inside a symbol's own history are forward-filled (holidays and
    halts, where the symbol simply did not trade); leading NaNs are left alone
    so `eligible` reads them as 'not listed yet'.
    """
    data_dir = data_dir or (PROJECT_ROOT / "data" / "daily")
    files = sorted(Path(data_dir).glob("*_1day.csv"))
    if not files:
        raise FileNotFoundError(
            f"No daily data in {data_dir}. Run:\n"
            f"  python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15"
        )

    cols = {"open": {}, "high": {}, "low": {}, "close": {}, "volume": {}}
    for f in files:
        sym = f.stem.replace("_1day", "")
        df = pd.read_csv(f, parse_dates=["datetime"]).set_index("datetime")
        df.index = df.index.tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        for c in cols:
            cols[c][sym] = df[c]

    panel = {c: pd.DataFrame(v).sort_index() for c, v in cols.items()}

    # Drop dates where the cross-section collapses - see MIN_CROSS_SECTION.
    coverage = panel["close"].notna().sum(axis=1)
    dropped = sorted(coverage[(coverage > 0) & (coverage < min_cross_section)].index)
    keep = coverage >= min_cross_section
    panel = {c: v.loc[keep] for c, v in panel.items()}

    events = {}
    if repair_corporate_actions:
        events = detect_price_steps(panel["close"])
        for sym, hits in events.items():
            if sym not in panel["close"].columns:
                continue
            last = max(ts for ts, _, _ in hits)
            for c in panel:
                panel[c].loc[panel[c].index < last, sym] = np.nan

    # Forward-fill interior gaps only.
    for c in panel:
        seen = panel[c].notna().cumsum() > 0
        panel[c] = panel[c].ffill().where(seen)

    if report:
        return panel, {"dropped_dates": dropped, "corporate_actions": events}
    return panel


def restrict(panel: dict, symbols) -> dict:
    """Narrow a panel to a symbol subset - used to screen inside the intraday 50."""
    keep = [s for s in symbols if s in panel["close"].columns]
    return {c: v[keep] for c, v in panel.items()}


def true_range(panel: dict) -> pd.DataFrame:
    """Daily true range. The overnight gap IS legitimate range on a daily bar."""
    h, l, c = panel["high"], panel["low"], panel["close"]
    pc = c.shift(1)
    return pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()]).groupby(level=0).max()
