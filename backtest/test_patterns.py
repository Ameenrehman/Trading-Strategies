"""
Fix NR7 date mapping and test:
1. NR7 (Narrowest Range of 7 days) Breakout
2. Inside Day (Harami / Inside Bar) Breakout
3. High Relative Volume (RVOL) Breakout (> 2.0x volume expansion on first 15 mins)
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


def add_daily_patterns(df_5min):
    """Calculate daily metrics and map them cleanly to 5-min bars."""
    df_temp = df_5min.copy()
    df_temp['date'] = df_temp.index.date

    # Daily aggregation
    daily = df_temp.groupby('date').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    })
    
    daily['range'] = daily['High'] - daily['Low']
    daily['min_7_range'] = daily['range'].rolling(7, min_periods=7).min()
    daily['is_nr7'] = daily['range'] == daily['min_7_range']
    daily['is_inside'] = (daily['High'] < daily['High'].shift(1)) & (daily['Low'] > daily['Low'].shift(1))

    # Shift by 1 because we trade TODAY based on YESTERDAY's pattern
    daily['nr7_yesterday'] = daily['is_nr7'].shift(1).fillna(False)
    daily['inside_yesterday'] = daily['is_inside'].shift(1).fillna(False)
    daily['prev_close'] = daily['Close'].shift(1)
    daily['prev_high'] = daily['High'].shift(1)
    daily['prev_low'] = daily['Low'].shift(1)

    # Map back to 5-min DataFrame
    nr7_map = daily['nr7_yesterday'].to_dict()
    inside_map = daily['inside_yesterday'].to_dict()
    prev_close_map = daily['prev_close'].to_dict()
    prev_high_map = daily['prev_high'].to_dict()
    prev_low_map = daily['prev_low'].to_dict()

    df_5min['is_nr7'] = [nr7_map.get(d, False) for d in df_temp['date']]
    df_5min['is_inside'] = [inside_map.get(d, False) for d in df_temp['date']]
    df_5min['prev_close'] = [prev_close_map.get(d, np.nan) for d in df_temp['date']]
    df_5min['prev_high'] = [prev_high_map.get(d, np.nan) for d in df_temp['date']]
    df_5min['prev_low'] = [prev_low_map.get(d, np.nan) for d in df_temp['date']]

    return df_5min


# -------------------------------------------------------------
# 1. NR7 & Inside Bar Breakout Strategy
# -------------------------------------------------------------
class CompressionBreakoutStrategy(Strategy):
    """Trade 15-min range breakout on days following NR7 or Inside Bar."""
    or_bars = 3  # 15 mins (3 x 5-min bars)
    sl_mult = 1.2
    rr_ratio = 2.0

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
        self.is_inside = self.I(lambda: self.data.df['is_inside'].values)

        self._current_date = None
        self._first_range_high = -np.inf
        self._first_range_low = np.inf
        self._bar_count = 0
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._bar_count = 0
            self._first_range_high = -np.inf
            self._first_range_low = np.inf
            self._traded_today = False

        self._bar_count += 1

        if self._bar_count <= self.or_bars:
            self._first_range_high = max(self._first_range_high, self.data.High[-1])
            self._first_range_low = min(self._first_range_low, self.data.Low[-1])
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

        # Condition: Yesterday was NR7 or Inside Bar
        compressed = self.is_nr7[-1] or self.is_inside[-1]
        if not compressed or bar_time_mins > 690 or self._traded_today:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]

        if price > self._first_range_high:
            self._traded_today = True
            sl = price - (atr * self.sl_mult)
            if sl < price:
                self.buy(sl=sl)
            return

        if price < self._first_range_low:
            self._traded_today = True
            sl = price + (atr * self.sl_mult)
            if price < sl:
                self.sell(sl=sl)
            return


# -------------------------------------------------------------
# 2. Previous Day High/Low Breakout (Camarilla / Floor Pivots style)
# -------------------------------------------------------------
class PrevDayBreakoutStrategy(Strategy):
    """Breakout of Yesterday's High or Low with volume confirmation."""
    def init(self):
        def calc_atr(high, low, close, period=14):
            tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
            tr[0] = high[0] - low[0]
            return pd.Series(tr).rolling(period, min_periods=1).mean().values

        def calc_ema(s, n):
            return pd.Series(s).ewm(span=n, adjust=False).mean().values

        self.atr = self.I(calc_atr, self.data.High, self.data.Low, self.data.Close, 14)
        self.ema20 = self.I(calc_ema, self.data.Close, 20)
        self.prev_high = self.I(lambda: self.data.df['prev_high'].values)
        self.prev_low = self.I(lambda: self.data.df['prev_low'].values)

        self._current_date = None
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._traded_today = False

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

        if bar_time_mins < 570 or bar_time_mins > 720 or self._traded_today:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]
        p_high = self.prev_high[-1]
        p_low = self.prev_low[-1]

        if not np.isnan(p_high) and price > p_high:
            self._traded_today = True
            sl = price - (atr * 1.5)
            if sl < price:
                self.buy(sl=sl)
            return

        if not np.isnan(p_low) and price < p_low:
            self._traded_today = True
            sl = price + (atr * 1.5)
            if price < sl:
                self.sell(sl=sl)
            return


# -------------------------------------------------------------
# Runner
# -------------------------------------------------------------
def run():
    print("=" * 75)
    print("  STRATEGY 1: Volatility Compression Breakout (NR7 / Inside Bar)")
    print("=" * 75)
    res1 = []
    for sym in STOCKS:
        data_raw = load_data(f"data/{sym}_5min.csv")
        data_proc = add_daily_patterns(data_raw)
        bt = Backtest(data_proc, CompressionBreakoutStrategy, cash=100_000, commission=COMMISSION,
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
    print(f"  --> Avg Return: {df1['return'].mean():+.2f}%, Avg Sharpe: {df1['sharpe'].mean():.3f}, Avg Trades: {df1['trades'].mean():.0f}\n")

    print("=" * 75)
    print("  STRATEGY 2: Previous Day High / Low Breakout")
    print("=" * 75)
    res2 = []
    for sym in STOCKS:
        data_raw = load_data(f"data/{sym}_5min.csv")
        data_proc = add_daily_patterns(data_raw)
        bt = Backtest(data_proc, PrevDayBreakoutStrategy, cash=100_000, commission=COMMISSION,
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
    print(f"  --> Avg Return: {df2['return'].mean():+.2f}%, Avg Sharpe: {df2['sharpe'].mean():.3f}, Avg Trades: {df2['trades'].mean():.0f}")


if __name__ == "__main__":
    run()
