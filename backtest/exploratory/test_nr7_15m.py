"""
Testing 15-Minute Timeframe & Volatility Compression (NR4/NR7) Breakouts:
1. 15-Min ORB (First 15-min bar breakout, with 1.5 ATR stop, trailing with 15m 9-EMA)
2. Daily NR4/NR7 Volatility Compression Breakout (Trade only after compressed days)
3. 15-Min Supertrend Trend Follower
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.gap_rvol_orb.run_backtest import load_data
from backtest.costs import per_side_commission

COMMISSION = per_side_commission(50_000)
STOCKS = ["SBIN", "RELIANCE", "TCS", "HDFCBANK", "INFY"]


def resample_to_15min(df_5min):
    """Resample 5-min OHLCV to 15-min OHLCV cleanly."""
    resampled = df_5min.resample('15min').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()
    # Filter only market hours
    resampled = resampled.between_time('09:15', '15:30')
    return resampled


# -------------------------------------------------------------
# 1. 15-Min ORB with 9-EMA Trailing Exit
# -------------------------------------------------------------
class ORB15MinTrailing(Strategy):
    """
    15-Min ORB:
    - First 15-min candle (9:15 - 9:30) defines the range.
    - Long on close > bar 1 High, Short on close < bar 1 Low.
    - Stop Loss = 1.5 * ATR.
    - Trailing exit: Close below 9 EMA for longs, Close above 9 EMA for shorts.
    - Force close at 15:15.
    """
    sl_atr_mult = 1.5
    ema_length = 9

    def init(self):
        def calc_atr(high, low, close, period=14):
            tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
            tr[0] = high[0] - low[0]
            return pd.Series(tr).rolling(period, min_periods=1).mean().values

        def calc_ema(s, n):
            return pd.Series(s).ewm(span=n, adjust=False).mean().values

        self.atr = self.I(calc_atr, self.data.High, self.data.Low, self.data.Close, 14)
        self.ema = self.I(calc_ema, self.data.Close, self.ema_length)

        self._current_date = None
        self._first_bar_high = -np.inf
        self._first_bar_low = np.inf
        self._bar_count = 0
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._bar_count = 0
            self._first_bar_high = -np.inf
            self._first_bar_low = np.inf
            self._traded_today = False

        self._bar_count += 1

        # First 15-min candle
        if self._bar_count == 1:
            self._first_bar_high = self.data.High[-1]
            self._first_bar_low = self.data.Low[-1]
            return

        # Trailing exit & EOD exit
        if self.position:
            if bar_time_mins >= 915:
                self.position.close()
                return
            if self.position.is_long and self.data.Close[-1] < self.ema[-1]:
                self.position.close()
                return
            if self.position.is_short and self.data.Close[-1] > self.ema[-1]:
                self.position.close()
                return
            return

        if bar_time_mins > 720 or self._traded_today:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]
        sl_dist = atr * self.sl_atr_mult

        if price > self._first_bar_high:
            self._traded_today = True
            sl = price - sl_dist
            if sl < price:
                self.buy(sl=sl)
            return

        if price < self._first_bar_low:
            self._traded_today = True
            sl = price + sl_dist
            if price < sl:
                self.sell(sl=sl)
            return


# -------------------------------------------------------------
# 2. NR7 / Volatility Compression Breakout
# -------------------------------------------------------------
class NR7BreakoutStrategy(Strategy):
    """
    Trade opening range breakout ONLY on days where the previous day was an NR7
    (Narrowest Daily Range of the last 7 days). Volatility compression leads to expansion.
    """
    def init(self):
        def calc_atr(high, low, close, period=14):
            tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
            tr[0] = high[0] - low[0]
            return pd.Series(tr).rolling(period, min_periods=1).mean().values

        def calc_ema(s, n):
            return pd.Series(s).ewm(span=n, adjust=False).mean().values

        self.atr = self.I(calc_atr, self.data.High, self.data.Low, self.data.Close, 14)
        self.ema20 = self.I(calc_ema, self.data.Close, 20)
        self.is_nr7 = self.I(lambda: self.data.df['is_nr7'].values)

        self._current_date = None
        self._first_bar_high = -np.inf
        self._first_bar_low = np.inf
        self._bar_count = 0
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._bar_count = 0
            self._first_bar_high = -np.inf
            self._first_bar_low = np.inf
            self._traded_today = False

        self._bar_count += 1

        if self._bar_count == 1:
            self._first_bar_high = self.data.High[-1]
            self._first_bar_low = self.data.Low[-1]
            return

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

        # ONLY TRADE IF PREVIOUS DAY WAS NR7
        if not self.is_nr7[-1] or bar_time_mins > 720 or self._traded_today:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]

        if price > self._first_bar_high:
            self._traded_today = True
            sl = price - (atr * 1.5)
            if sl < price:
                self.buy(sl=sl)
            return

        if price < self._first_bar_low:
            self._traded_today = True
            sl = price + (atr * 1.5)
            if price < sl:
                self.sell(sl=sl)
            return


def add_nr7_column(df_5min):
    """Compute daily range and flag if yesterday was NR7."""
    daily = df_5min.resample('D').agg({'High': 'max', 'Low': 'min', 'Close': 'last'}).dropna()
    daily['range'] = daily['High'] - daily['Low']
    daily['min_7_range'] = daily['range'].rolling(7).min()
    daily['is_nr7_today'] = daily['range'] == daily['min_7_range']
    daily['is_nr7_for_next_day'] = daily['is_nr7_today'].shift(1).fillna(False)

    df_copy = df_5min.copy()
    df_copy['date_only'] = df_copy.index.date
    daily_map = daily['is_nr7_for_next_day'].to_dict()
    df_copy['is_nr7'] = [daily_map.get(pd.Timestamp(d), False) for d in df_copy['date_only']]
    df_copy = df_copy.drop(columns=['date_only'])
    return df_copy


def test_suite():
    print("=" * 75)
    print("  STRATEGY 1: 15-Minute ORB + 9 EMA Trailing Exit")
    print("=" * 75)
    res1 = []
    for sym in STOCKS:
        data_5m = load_data(f"data/intraday_5min/{sym}_5min.csv")
        data_15m = resample_to_15min(data_5m)
        bt = Backtest(data_15m, ORB15MinTrailing, cash=100_000, commission=COMMISSION,
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
    print("  STRATEGY 2: NR7 Volatility Compression Breakout (5-min)")
    print("=" * 75)
    res2 = []
    for sym in STOCKS:
        data_5m = load_data(f"data/intraday_5min/{sym}_5min.csv")
        data_nr7 = add_nr7_column(data_5m)
        bt = Backtest(data_nr7, NR7BreakoutStrategy, cash=100_000, commission=COMMISSION,
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
    test_suite()
