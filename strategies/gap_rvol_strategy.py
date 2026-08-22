"""
Dynamic Gap + RVOL Momentum strategy.

This is the strategy phase-1-backtesting.md section 5 argues for: instead of
trading a fixed ticker every morning, only trade sessions where the stock has
actually gapped and is trading on unusually heavy opening volume, then hold
with a trailing stop so the trade can capture a meaningful share of the day's
range rather than being clipped by a fixed 2:1 target.

The reasoning (section 5, Lever 1): cost is roughly fixed per trade, so the
only structural way past it is to take fewer, bigger setups. Median daily
range on these names is only 142-192 bps, and the cost hurdle is 10-15% of
that, so a strategy has to capture roughly a fifth of the day's range to net
anything.

Rules
-----
- Session qualifies if |overnight gap| >= min_gap_pct.
- Optional RVOL filter: opening-range volume must be >= rvol_mult x the median
  opening-range volume of the previous rvol_lookback sessions.
- Optional daily-trend filter: only take gap-ups above the trend EMA and
  gap-downs below it.
- Direction is the gap direction (continuation, not fade).
- Entry: resting stop order at the opening-range extreme in the gap direction.
- Initial stop: opposite side of the opening range, or an ATR multiple.
- Exit: ATR chandelier trailing stop, or a fixed RR target if trail_atr_mult
  is 0. Everything flat at eod_exit_time or the last bar of the session.
- Size: fixed fractional risk.
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from strategies.session import session_arrays, day_aware_atr, risk_based_size


def _daily_series(values, day_id, how="first"):
    """Collapse a per-bar array to one value per day, then broadcast back."""
    s = pd.Series(values).groupby(day_id)
    agg = s.first() if how == "first" else (s.last() if how == "last" else s.sum())
    return agg


class GapRVOLMomentum(Strategy):
    """
    Parameters
    ----------
    min_gap_pct : float
        Minimum |overnight gap| in % required to trade the session.
    max_gap_pct : float
        Skip runaway news gaps above this size (0 disables the cap).
    or_minutes : int
        Opening-range length in minutes (default 15).
    rvol_mult : float
        Required opening-range volume as a multiple of the trailing median.
        Set to 0 to disable the RVOL filter.
    rvol_lookback : int
        Sessions used for the trailing median opening-range volume.
    use_trend_filter : bool
        Require gap-ups above the trend EMA and gap-downs below it.
    trend_ema : int
        EMA period (in 5-min bars) for the trend filter.
    atr_stop_mult : float
        ATR multiple for the initial stop. 0 uses the opposite range side.
    trail_atr_mult : float
        ATR multiple for the chandelier trailing stop. 0 disables trailing and
        uses a fixed rr_ratio target instead.
    rr_ratio : float
        Fixed reward:risk target, used only when trail_atr_mult is 0.
    risk_pct, leverage, max_entry_time, eod_exit_time
        As in ORBStrategy.
    """

    min_gap_pct = 1.0
    max_gap_pct = 0.0
    or_minutes = 15
    rvol_mult = 0.0
    rvol_lookback = 20
    use_trend_filter = False
    trend_ema = 100
    atr_stop_mult = 0.0
    trail_atr_mult = 2.0
    rr_ratio = 2.0
    risk_pct = 0.01
    leverage = 5.0
    max_entry_time = 750
    eod_exit_time = 915

    def init(self):
        idx = self.data.index
        s = session_arrays(idx)
        self._tod = s["tod"]
        self._day_id = s["day_id"]
        self._is_first_bar = s["is_first_bar"]
        self._is_last_bar = s["is_last_bar"]
        self._session_start = s["session_start"]

        close = np.asarray(self.data.Close, dtype=float)
        open_ = np.asarray(self.data.Open, dtype=float)
        vol = np.asarray(self.data.Volume, dtype=float)
        day_id = self._day_id

        self._atr = day_aware_atr(self.data.High, self.data.Low, close,
                                  self._is_first_bar, period=14)

        # --- Overnight gap, one value per day, broadcast to every bar -------
        day_open = _daily_series(open_, day_id, "first")
        day_close = _daily_series(close, day_id, "last")
        prev_close = day_close.shift(1)
        gap = ((day_open - prev_close) / prev_close * 100.0).to_numpy()
        self._gap_pct = np.nan_to_num(gap[day_id], nan=0.0)

        # --- Opening-range volume and RVOL ---------------------------------
        in_or = self._tod < self._session_start + self.or_minutes
        or_vol = pd.Series(np.where(in_or, vol, 0.0)).groupby(day_id).sum()
        # Trailing median of *previous* sessions only - no look-ahead.
        med = or_vol.shift(1).rolling(self.rvol_lookback, min_periods=5).median()
        with np.errstate(divide="ignore", invalid="ignore"):
            rvol = (or_vol / med).to_numpy()
        self._rvol = np.nan_to_num(rvol[day_id], nan=0.0)

        # --- Trend filter EMA ----------------------------------------------
        self._ema = pd.Series(close).ewm(span=self.trend_ema, adjust=False).mean().to_numpy()

        self._range_high = -np.inf
        self._range_low = np.inf
        self._current_day = -1
        self._opened_today = False
        self._orders_placed_today = False
        self._peak = np.nan
        self._trough = np.nan
        self._init_stop = np.nan

    # -- helpers ---------------------------------------------------------

    def _cancel_pending(self):
        for order in list(self.orders):
            if not order.is_contingent:
                order.cancel()

    def _reset_day(self, i):
        self._current_day = self._day_id[i]
        self._range_high = -np.inf
        self._range_low = np.inf
        self._opened_today = False
        self._orders_placed_today = False
        self._peak = np.nan
        self._trough = np.nan
        self._init_stop = np.nan

    def _qualifies(self, i):
        gap = self._gap_pct[i]
        if abs(gap) < self.min_gap_pct:
            return 0
        if self.max_gap_pct and abs(gap) > self.max_gap_pct:
            return 0
        if self.rvol_mult and self._rvol[i] < self.rvol_mult:
            return 0

        direction = 1 if gap > 0 else -1

        if self.use_trend_filter:
            price = self.data.Close[-1]
            ema = self._ema[i]
            if direction > 0 and not price > ema:
                return 0
            if direction < 0 and not price < ema:
                return 0

        return direction

    # -- main loop -------------------------------------------------------

    def next(self):
        i = len(self.data) - 1
        tod = self._tod[i]

        if self._day_id[i] != self._current_day:
            self._reset_day(i)

        if self.position:
            self._opened_today = True

        # --- Forced flatten -------------------------------------------------
        if tod >= self.eod_exit_time or self._is_last_bar[i]:
            self._cancel_pending()
            if self.position:
                self.position.close()
            return

        # --- Trailing stop management --------------------------------------
        if self.position and self.trail_atr_mult:
            atr = self._atr[i]
            if np.isfinite(atr) and atr > 0:
                for trade in self.trades:
                    if trade.is_long:
                        self._peak = np.nanmax([self._peak, self.data.High[-1]])
                        new_sl = self._peak - atr * self.trail_atr_mult
                        # Only ever ratchet in the favourable direction.
                        if trade.sl is None or new_sl > trade.sl:
                            if new_sl < self.data.Close[-1]:
                                trade.sl = new_sl
                    else:
                        self._trough = np.nanmin([self._trough, self.data.Low[-1]])
                        new_sl = self._trough + atr * self.trail_atr_mult
                        if trade.sl is None or new_sl < trade.sl:
                            if new_sl > self.data.Close[-1]:
                                trade.sl = new_sl

        # --- Build the opening range ---------------------------------------
        if tod < self._session_start[i] + self.or_minutes:
            self._range_high = max(self._range_high, self.data.High[-1])
            self._range_low = min(self._range_low, self.data.Low[-1])
            return

        if tod > self.max_entry_time:
            self._cancel_pending()
            return

        if self.position:
            self._cancel_pending()
            return

        if self._opened_today or self._orders_placed_today:
            return

        direction = self._qualifies(i)
        if direction == 0:
            return

        range_size = self._range_high - self._range_low
        if not np.isfinite(range_size) or range_size <= 0:
            return

        atr = self._atr[i]
        if not np.isfinite(atr) or atr <= 0:
            atr = range_size

        if direction > 0:
            entry = self._range_high
            stop = (entry - atr * self.atr_stop_mult) if self.atr_stop_mult else self._range_low
            if stop >= entry:
                return
            size = risk_based_size(self.equity, self.risk_pct, entry, stop, self.leverage)
            if size < 1:
                return
            tp = None if self.trail_atr_mult else entry + (entry - stop) * self.rr_ratio
            self.buy(size=size, stop=entry, sl=stop, tp=tp)
        else:
            entry = self._range_low
            stop = (entry + atr * self.atr_stop_mult) if self.atr_stop_mult else self._range_high
            if stop <= entry:
                return
            size = risk_based_size(self.equity, self.risk_pct, entry, stop, self.leverage)
            if size < 1:
                return
            tp = None if self.trail_atr_mult else entry - (stop - entry) * self.rr_ratio
            self.sell(size=size, stop=entry, sl=stop, tp=tp)

        self._init_stop = stop
        self._orders_placed_today = True
