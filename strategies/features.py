"""
The feature library: everything computable from daily OHLCV at the close of day D.

One definition, shared by the study that measured these features and the strategy
that trades them. Duplicating them invites the two to drift apart, and a strategy
scored on a feature it does not actually compute is the quietest way to publish a
number that was never real.

Every frame returned is point-in-time: row D uses only data through D's close.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Eligibility - liquid, real-priced, enough history to compute a 200-day mean.
MIN_PRICE, MAX_PRICE = 50.0, 5000.0
MIN_ADV = 5e7          # Rs.5 crore of 20-day average traded value
MIN_HISTORY = 250

ATR_PERIOD = 14


# ---------------------------------------------------------------------------
# Feature construction - everything here is knowable at the close of day D.
# ---------------------------------------------------------------------------

def _wilder(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def build_features(panel: dict) -> tuple[dict, pd.DataFrame]:
    """Return (features, atr). Each feature frame is indexed date x symbol."""
    o, h, l, c, v = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    pc = c.shift(1)

    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()]).groupby(level=0).max()
    atr = _wilder(tr, ATR_PERIOD)

    diff = c.diff()
    gain = _wilder(diff.clip(lower=0), ATR_PERIOD)
    loss = _wilder((-diff).clip(lower=0), ATR_PERIOD)
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    rng = (h - l).replace(0, np.nan)

    feats = {
        # --- trend / momentum, at several speeds ---
        "ret1":       c / pc - 1,
        "ret5":       c / c.shift(5) - 1,
        "ret20":      c / c.shift(20) - 1,
        "ret60skip5": c.shift(5) / c.shift(65) - 1,
        "dist_ma20":  c / c.rolling(20).mean() - 1,
        "dist_ma50":  c / c.rolling(50).mean() - 1,
        "dist_ma200": c / c.rolling(200).mean() - 1,
        "rsi14":      rsi,
        "updays5":    (c > pc).rolling(5).sum(),

        # --- resistance / support structure ---
        "high_prox":  c / h.rolling(20).max(),      # ~1.0 = pressed against resistance
        "low_prox":   c / l.rolling(20).min(),      # ~1.0 = sitting on support
        "clv":        (c - l) / rng,                # where in today's range it closed

        # --- volume ---
        "vol_ratio":  v / v.rolling(20).mean(),
        "turnover":   np.log((c * v).clip(lower=1)),

        # --- volatility / today's character ---
        "atr_pct":    atr / c,
        "tr_ratio":   tr / atr,
        "gap_today":  o / pc - 1,
    }
    return feats, atr


def eligibility(panel: dict) -> pd.DataFrame:
    c, v = panel["close"], panel["volume"]
    adv = (c * v).rolling(20).mean()
    history = c.notna().cumsum()
    return (
        c.notna()
        & (c >= MIN_PRICE) & (c <= MAX_PRICE)
        & (adv >= MIN_ADV)
        & (history >= MIN_HISTORY)
    )
