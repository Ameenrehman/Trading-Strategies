"""
Opening Range Breakout (ORB) Strategy for Backtesting.py.

Candidate A from phase-1-backtesting.md. This is the post-fix version: the
original implementation had eight defects catalogued in
Learning-T/phase-1-backtesting.md section 2, all addressed here.

Rules
-----
- Opening range: high/low of the first `or_minutes` of the session, measured
  by clock time rather than bar count.
- Entry: resting stop orders at the range high (long) and range low (short),
  so the fill is at the breakout level, not at the close of whichever bar
  happened to break it.
- Stop: opposite side of the range, or an ATR-based distance.
- Target: `rr_ratio` x the actual entry-to-stop distance.
- Size: fixed fractional risk (`risk_pct` of equity per trade).
- No new entries after `max_entry_time`; everything flat by `eod_exit_time`
  or the final bar of the session, whichever comes first.

What changed from the original (defect numbers match the Phase 1 doc)
---------------------------------------------------------------------
#1  Position size is risk-based instead of Backtesting.py's default ~100%
    of equity, so trades are comparable in R-multiples.
#3  The old stop was `min(range_low, price - 0.5*range)`, whose second term
    could never bind - the stop was always the range low while the target was
    sized off `range_size`, making realised RR 1.87 rather than the configured
    2.0. Target is now sized off the true entry-to-stop distance.
#4  The "already traded today" flag is set when a position actually opens,
    not when an order is merely considered, so a rejected order no longer
    burns the session.
#5  ATR is day-aware (see strategies/session.py).
#6  End-of-day exit fires on the last bar of the session as well as on the
    clock, so positions cannot leak overnight on a truncated feed.
#7  The opening range is keyed to timestamps, not bar counts.
#8  Entry is a stop order at the breakout level rather than a close-of-bar
    market fill.
"""

import numpy as np
from backtesting import Strategy

from strategies.session import session_arrays, day_aware_atr, risk_based_size


class ORBStrategy(Strategy):
    """
    Opening Range Breakout strategy.

    Parameters
    ----------
    or_minutes : int
        Length of the opening range in minutes from the session open (default
        30, i.e. 9:15-9:45 IST).
    rr_ratio : float
        Reward-to-risk ratio for the take-profit (default 2.0).
    min_range_pct : float
        Skip the day if the opening range is smaller than this % of price.
    max_entry_time : int
        Latest entry time, in minutes from midnight (default 750 = 12:30 PM).
    eod_exit_time : int
        Forced flatten time, in minutes from midnight (default 915 = 15:15).
    use_atr_stop : bool
        Use an ATR-multiple stop instead of the opposite range side.
    atr_mult : float
        ATR multiplier when use_atr_stop is True.
    risk_pct : float
        Fraction of equity risked per trade (default 0.01 = 1%).
    leverage : float
        Intraday MIS leverage assumed when capping size (default 5x). Must
        match the `margin` passed to Backtest (margin = 1 / leverage).
    allow_long, allow_short : bool
        Enable each side.
    """

    or_minutes = 30
    rr_ratio = 2.0
    min_range_pct = 0.0
    max_entry_time = 750
    eod_exit_time = 915
    use_atr_stop = False
    atr_mult = 1.5
    risk_pct = 0.01
    leverage = 5.0
    allow_long = True
    allow_short = True

    def init(self):
        idx = self.data.index
        s = session_arrays(idx)
        self._tod = s["tod"]
        self._day_id = s["day_id"]
        self._is_first_bar = s["is_first_bar"]
        self._is_last_bar = s["is_last_bar"]
        self._session_start = s["session_start"]

        self._atr = day_aware_atr(
            self.data.High, self.data.Low, self.data.Close,
            self._is_first_bar, period=14,
        )

        self._range_high = np.nan
        self._range_low = np.nan
        self._current_day = -1
        self._opened_today = False
        self._orders_placed_today = False

    # -- helpers ---------------------------------------------------------

    def _cancel_pending(self):
        """Cancel any resting entry orders (contingent SL/TP are untouched)."""
        for order in list(self.orders):
            if not order.is_contingent:
                order.cancel()

    def _reset_day(self, i):
        self._current_day = self._day_id[i]
        self._range_high = -np.inf
        self._range_low = np.inf
        self._opened_today = False
        self._orders_placed_today = False

    # -- main loop -------------------------------------------------------

    def next(self):
        i = len(self.data) - 1
        tod = self._tod[i]

        if self._day_id[i] != self._current_day:
            self._reset_day(i)

        # Track whether a position actually opened today (defect #4): the flag
        # follows real fills, not intentions.
        if self.position:
            self._opened_today = True

        # --- Forced flatten: clock time OR the final bar of the session -----
        # The second condition is what stops positions leaking overnight on a
        # truncated feed (defect #6).
        if tod >= self.eod_exit_time or self._is_last_bar[i]:
            self._cancel_pending()
            if self.position:
                self.position.close()
            return

        # --- Build the opening range by clock time (defect #7) --------------
        if tod < self._session_start[i] + self.or_minutes:
            self._range_high = max(self._range_high, self.data.High[-1])
            self._range_low = min(self._range_low, self.data.Low[-1])
            return

        # --- Stop accepting new entries after the cutoff -------------------
        if tod > self.max_entry_time:
            self._cancel_pending()
            return

        # One position per day; once we're in, drop the unfilled opposite side.
        if self.position:
            self._cancel_pending()
            return

        if self._opened_today or self._orders_placed_today:
            return

        range_size = self._range_high - self._range_low
        if not np.isfinite(range_size) or range_size <= 0:
            return

        mid = (self._range_high + self._range_low) / 2.0
        if (range_size / mid) * 100.0 < self.min_range_pct:
            return

        atr = self._atr[i]
        if not np.isfinite(atr) or atr <= 0:
            atr = range_size

        placed = False

        # --- Long: resting stop-buy at the range high (defect #8) ----------
        if self.allow_long:
            entry = self._range_high
            stop = entry - atr * self.atr_mult if self.use_atr_stop else self._range_low
            if stop < entry:
                risk = entry - stop                      # true risk (defect #3)
                size = risk_based_size(self.equity, self.risk_pct, entry, stop,
                                       self.leverage)    # (defect #1)
                if size >= 1:
                    self.buy(size=size, stop=entry, sl=stop,
                             tp=entry + risk * self.rr_ratio)
                    placed = True

        # --- Short: resting stop-sell at the range low ---------------------
        if self.allow_short:
            entry = self._range_low
            stop = entry + atr * self.atr_mult if self.use_atr_stop else self._range_high
            if stop > entry:
                risk = stop - entry
                size = risk_based_size(self.equity, self.risk_pct, entry, stop,
                                       self.leverage)
                if size >= 1:
                    self.sell(size=size, stop=entry, sl=stop,
                              tp=entry - risk * self.rr_ratio)
                    placed = True

        # Orders rest for the remainder of the session; don't re-place them
        # every bar or we'd stack duplicates.
        if placed:
            self._orders_placed_today = True
