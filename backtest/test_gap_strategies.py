"""
Deep optimization of Gap & Momentum Strategies on 2-Year Intraday NSE Data:
1. Gap Fade (Mean Reversion / Gap Fill)
2. Gap Continuation with Trailing ATR / EMA Exit
3. Daily Trend Aligned Gap ORB
4. Higher-Timeframe (15m/1h) Multi-Timeframe Momentum
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.run_backtest import load_data
from backtest.costs import per_side_commission

COMMISSION = per_side_commission(50_000)
STOCKS = ["SBIN", "RELIANCE", "TCS", "HDFCBANK", "INFY"]


# -------------------------------------------------------------
# Strategy 1: Gap Fade (Gap Fill Strategy)
# If stock gaps UP > 0.4%, sell when price drops below first 5-min candle low (target = previous day close).
# If stock gaps DOWN < -0.4%, buy when price rises above first 5-min candle high.
# -------------------------------------------------------------
class GapFadeStrategy(Strategy):
    min_gap_pct = 0.4
    max_gap_pct = 2.0  # Avoid runaway news gaps
    sl_mult = 1.0      # SL above first candle high / below low

    def init(self):
        self._prev_day_close = None
        self._current_date = None
        self._day_open = None
        self._gap_pct = 0.0
        self._first_bar_high = -np.inf
        self._first_bar_low = np.inf
        self._bar_count = 0
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            if self._current_date is not None:
                self._prev_day_close = self.data.Close[-2]
            self._current_date = bar_date
            self._day_open = self.data.Open[-1]
            self._bar_count = 0
            self._first_bar_high = self.data.High[-1]
            self._first_bar_low = self.data.Low[-1]
            self._traded_today = False

            if self._prev_day_close is not None and self._prev_day_close > 0:
                self._gap_pct = ((self._day_open - self._prev_day_close) / self._prev_day_close) * 100.0
            else:
                self._gap_pct = 0.0

        self._bar_count += 1

        if self._bar_count == 1:
            self._first_bar_high = self.data.High[-1]
            self._first_bar_low = self.data.Low[-1]
            return

        if bar_time_mins >= 915:
            if self.position:
                self.position.close()
            return

        if bar_time_mins > 690 or self._traded_today or self.position:
            return

        price = self.data.Close[-1]
        target = self._prev_day_close

        # Gap UP -> Fade (Short) when breaking first bar low, targeting previous close
        if self.min_gap_pct <= self._gap_pct <= self.max_gap_pct:
            if price < self._first_bar_low and target < price:
                self._traded_today = True
                sl = self._first_bar_high + (self._first_bar_high - self._first_bar_low) * self.sl_mult
                tp = target
                if tp < price < sl:
                    self.sell(sl=sl, tp=tp)
                return

        # Gap DOWN -> Fade (Buy) when breaking first bar high, targeting previous close
        if -self.max_gap_pct <= self._gap_pct <= -self.min_gap_pct:
            if price > self._first_bar_high and target > price:
                self._traded_today = True
                sl = self._first_bar_low - (self._first_bar_high - self._first_bar_low) * self.sl_mult
                tp = target
                if sl < price < tp:
                    self.buy(sl=sl, tp=tp)
                return


# -------------------------------------------------------------
# Strategy 2: Daily Trend-Aligned Gap Continuation with Trailing Stop
# -------------------------------------------------------------
class TrendGapTrailing(Strategy):
    min_gap_pct = 0.3
    or_bars = 3
    atr_period = 14

    def init(self):
        def calc_ema(s, n):
            return pd.Series(s).ewm(span=n, adjust=False).mean().values

        def calc_atr(high, low, close, period=14):
            tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
            tr[0] = high[0] - low[0]
            return pd.Series(tr).rolling(period, min_periods=1).mean().values

        self.ema20 = self.I(calc_ema, self.data.Close, 20)
        self.ema100 = self.I(calc_ema, self.data.Close, 100)
        self.atr = self.I(calc_atr, self.data.High, self.data.Low, self.data.Close, 14)

        self._prev_day_close = None
        self._current_date = None
        self._gap_pct = 0.0
        self._range_high = -np.inf
        self._range_low = np.inf
        self._bar_count = 0
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            if self._current_date is not None:
                self._prev_day_close = self.data.Close[-2]
            self._current_date = bar_date
            self._bar_count = 0
            self._range_high = -np.inf
            self._range_low = np.inf
            self._traded_today = False

            if self._prev_day_close is not None and self._prev_day_close > 0:
                self._gap_pct = ((self.data.Open[-1] - self._prev_day_close) / self._prev_day_close) * 100.0
            else:
                self._gap_pct = 0.0

        self._bar_count += 1

        if self._bar_count <= self.or_bars:
            self._range_high = max(self._range_high, self.data.High[-1])
            self._range_low = min(self._range_low, self.data.Low[-1])
            return

        # Trailing exit logic: if long and price closes below EMA20, close; if short and price closes above EMA20, close
        if self.position:
            if bar_time_mins >= 915:
                self.position.close()
                return
            if self.position.is_long and self.data.Close[-1] < self.ema20[-1]:
                self.position.close()
                return
            if self.position.is_short and self.data.Close[-1] > self.ema20[-1]:
                self.position.close()
                return
            return

        if bar_time_mins > 690 or self._traded_today:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]

        # Trend Aligned Gap Continuation
        # Long: Gap Up + Stock > EMA100 + Breaks 15m Range High
        if self._gap_pct >= self.min_gap_pct and price > self.ema100[-1] and price > self._range_high:
            self._traded_today = True
            sl = price - (atr * 1.5)
            if sl < price:
                self.buy(sl=sl)
            return

        # Short: Gap Down + Stock < EMA100 + Breaks 15m Range Low
        if self._gap_pct <= -self.min_gap_pct and price < self.ema100[-1] and price < self._range_low:
            self._traded_today = True
            sl = price + (atr * 1.5)
            if price < sl:
                self.sell(sl=sl)
            return


# -------------------------------------------------------------
# Runner
# -------------------------------------------------------------
def test_both():
    print("=" * 75)
    print("  STRATEGY 1: Gap Fade (Gap Fill Strategy)")
    print("=" * 75)
    res1 = []
    for sym in STOCKS:
        data = load_data(f"data/intraday_5min/{sym}_5min.csv")
        bt = Backtest(data, GapFadeStrategy, cash=100_000, commission=COMMISSION,
                      exclusive_orders=True, trade_on_close=True)
        stats = bt.run()
        ret = stats.get("Return [%]", 0)
        wr = stats.get("Win Rate [%]", 0)
        trades = stats.get("# Trades", 0)
        pf = stats.get("Profit Factor", 0)
        sharpe = stats.get("Sharpe Ratio", 0)
        max_dd = stats.get("Max. Drawdown [%]", 0)
        pf_str = f"{pf:.3f}" if pf else "N/A"
        print(f"  {sym:10s} | Return: {ret:+6.2f}% | WinRate: {wr:4.1f}% | Trades: {trades:3d} | PF: {pf_str} | Sharpe: {sharpe:+6.3f} | MaxDD: {max_dd:5.2f}%")
        res1.append({"return": ret, "sharpe": sharpe, "trades": trades})

    df1 = pd.DataFrame(res1)
    print(f"  --> Avg Return: {df1['return'].mean():+.2f}%, Avg Sharpe: {df1['sharpe'].mean():.3f}\n")

    print("=" * 75)
    print("  STRATEGY 2: Trend-Aligned Gap Continuation with 20 EMA Trailing Exit")
    print("=" * 75)
    res2 = []
    for sym in STOCKS:
        data = load_data(f"data/intraday_5min/{sym}_5min.csv")
        bt = Backtest(data, TrendGapTrailing, cash=100_000, commission=COMMISSION,
                      exclusive_orders=True, trade_on_close=True)
        stats = bt.run()
        ret = stats.get("Return [%]", 0)
        wr = stats.get("Win Rate [%]", 0)
        trades = stats.get("# Trades", 0)
        pf = stats.get("Profit Factor", 0)
        sharpe = stats.get("Sharpe Ratio", 0)
        max_dd = stats.get("Max. Drawdown [%]", 0)
        pf_str = f"{pf:.3f}" if pf else "N/A"
        print(f"  {sym:10s} | Return: {ret:+6.2f}% | WinRate: {wr:4.1f}% | Trades: {trades:3d} | PF: {pf_str} | Sharpe: {sharpe:+6.3f} | MaxDD: {max_dd:5.2f}%")
        res2.append({"return": ret, "sharpe": sharpe, "trades": trades})

    df2 = pd.DataFrame(res2)
    print(f"  --> Avg Return: {df2['return'].mean():+.2f}%, Avg Sharpe: {df2['sharpe'].mean():.3f}")


if __name__ == "__main__":
    test_both()
