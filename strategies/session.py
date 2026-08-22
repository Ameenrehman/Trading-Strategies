"""
Shared intraday-session helpers for NSE strategies.

Everything here exists to fix defects that were found in the first Phase 1
results round (see Learning-T/phase-1-backtesting.md section 2):

- Session structure is derived from actual timestamps, never from bar counts,
  so a missing bar can't silently shift the opening-range window (defect #7).
- The last bar of each trading day is identified explicitly, so an end-of-day
  exit still fires on days whose feed is truncated (defect #6).
- ATR is computed day-aware, so the overnight gap is not counted as intraday
  true range on the first bar of a session (defect #5).
"""

import numpy as np
import pandas as pd


def session_arrays(index: pd.DatetimeIndex) -> dict:
    """
    Precompute per-bar session structure from a DatetimeIndex.

    Returns a dict of numpy arrays, all aligned to `index`:
      tod           - minutes from midnight (9:15 -> 555)
      day_id        - integer id, one per calendar trading day
      is_first_bar  - True on the first bar of each day
      is_last_bar   - True on the last bar of each day (whatever time it is)
      or_end_tod    - end of the opening-range window is added later by callers
      session_start - tod of that day's first bar, broadcast to every bar
    """
    tod = (index.hour * 60 + index.minute).to_numpy()
    day_key = index.normalize().to_numpy()

    # Integer day id: increments whenever the calendar date changes.
    day_id = np.zeros(len(index), dtype=np.int64)
    if len(index):
        changed = np.empty(len(index), dtype=bool)
        changed[0] = True
        changed[1:] = day_key[1:] != day_key[:-1]
        day_id = np.cumsum(changed) - 1

    is_first_bar = np.zeros(len(index), dtype=bool)
    is_last_bar = np.zeros(len(index), dtype=bool)
    if len(index):
        is_first_bar[0] = True
        is_first_bar[1:] = day_id[1:] != day_id[:-1]
        is_last_bar[-1] = True
        is_last_bar[:-1] = day_id[:-1] != day_id[1:]

    # Each day's opening time, broadcast across that day's bars.
    session_start = np.empty(len(index), dtype=np.int64)
    if len(index):
        starts = tod[is_first_bar]
        session_start = starts[day_id]

    return {
        "tod": tod,
        "day_id": day_id,
        "is_first_bar": is_first_bar,
        "is_last_bar": is_last_bar,
        "session_start": session_start,
    }


def day_aware_atr(high, low, close, is_first_bar, period=14):
    """
    ATR that does not treat the overnight gap as intraday range.

    On the first bar of a session there is no meaningful previous close, so
    true range is just high-low. Everywhere else it is the usual three-way max.
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    is_first_bar = np.asarray(is_first_bar, dtype=bool)

    prev_close = np.empty_like(close)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    # First bar of any session: overnight gap is not intraday range.
    tr[is_first_bar] = (high - low)[is_first_bar]

    return pd.Series(tr).rolling(period, min_periods=1).mean().to_numpy()


def risk_based_size(equity, risk_pct, entry_price, stop_price,
                    leverage=5.0, cash_buffer=0.95):
    """
    Fixed-fractional position size in whole shares.

    Risk `risk_pct` of current equity across the distance from entry to stop,
    which is what makes per-trade results comparable in R-multiples. Capped by
    the notional that intraday MIS leverage actually allows.

    Returns 0 when the trade is not takeable (invalid stop, or size rounds
    below one share) - callers should skip the trade in that case.
    """
    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share <= 0 or entry_price <= 0:
        return 0

    units = int((equity * risk_pct) / risk_per_share)
    max_units = int((equity * leverage * cash_buffer) / entry_price)
    units = min(units, max_units)

    return max(units, 0)
