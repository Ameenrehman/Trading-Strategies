"""
Testing Advanced High-Conviction Intraday Strategies for Indian Equities:
1. Candidate C: Gap + Opening Range Momentum (Only trades on significant Gap days)
2. Supertrend Multi-Timeframe Trend Follower (15m confirmation + 5m entry + trailing exit)
3. Volatility Compression / Inside Bar (NR4/NR7) Breakout
4. High-Momentum EMA Pullback with Trailing Stop
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
# Strategy A: Candidate C — Gap + Opening Range Continuation
# -------------------------------------------------------------
class GapORBContinuation(Strategy):
    """
    Candidate C: Only trade when stock gaps > min_gap_pct (e.g. 0.5% - 1.0%)
    and breaks the first 15-min range in the direction of the gap.
    """
    min_gap_pct = 0.5       # Min gap required
    or_bars = 3             # 3 x 5-min bars = 15 min opening range
    rr_ratio = 2.0
    sl_atr_mult = 1.2

    def init(self):
        def calc_atr(high, low, close, period=14):
            tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
            tr[0] = high[0] - low[0]
            return pd.Series(tr).rolling(period, min_periods=1).mean().values

        self.atr = self.I(calc_atr, self.data.High, self.data.Low, self.data.Close, 14)
        self._prev_day_close = None
        self._current_date = None
        self._day_open = None
        self._gap_pct = 0.0
        self._range_high = -np.inf
        self._range_low = np.inf
        self._bar_count = 0
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        # New day detection
        if bar_date != self._current_date:
            if self._current_date is not None:
                self._prev_day_close = self.data.Close[-2]
            self._current_date = bar_date
            self._day_open = self.data.Open[-1]
            self._bar_count = 0
            self._range_high = -np.inf
            self._range_low = np.inf
            self._traded_today = False

            if self._prev_day_close is not None and self._prev_day_close > 0:
                self._gap_pct = ((self._day_open - self._prev_day_close) / self._prev_day_close) * 100.0
            else:
                self._gap_pct = 0.0

        self._bar_count += 1

        # Build opening range
        if self._bar_count <= self.or_bars:
            self._range_high = max(self._range_high, self.data.High[-1])
            self._range_low = min(self._range_low, self.data.Low[-1])
            return

        # Force close at 15:15
        if bar_time_mins >= 915:
            if self.position:
                self.position.close()
            return

        # Entry cutoff at 11:30 AM (690 mins)
        if bar_time_mins > 690 or self._traded_today or self.position:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]
        risk = max(atr * self.sl_atr_mult, (self._range_high - self._range_low) * 0.5)

        # Bullish Gap continuation: Gap UP >= min_gap_pct and breaks 15-min high
        if self._gap_pct >= self.min_gap_pct and price > self._range_high:
            self._traded_today = True
            sl = price - risk
            tp = price + (risk * self.rr_ratio)
            if sl < price < tp:
                self.buy(sl=sl, tp=tp)
            return

        # Bearish Gap continuation: Gap DOWN <= -min_gap_pct and breaks 15-min low
        if self._gap_pct <= -self.min_gap_pct and price < self._range_low:
            self._traded_today = True
            sl = price + risk
            tp = price - (risk * self.rr_ratio)
            if tp < price < sl:
                self.sell(sl=sl, tp=tp)
            return


# -------------------------------------------------------------
# Strategy B: Supertrend Intraday Trend Following
# -------------------------------------------------------------
def calc_supertrend(df, period=10, multiplier=3.0):
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values
    
    # ATR
    tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr = pd.Series(tr).rolling(period, min_periods=1).mean().values

    hl2 = (high + low) / 2.0
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    supertrend = np.zeros(len(close))
    direction = np.zeros(len(close))  # 1 = Bullish, -1 = Bearish

    for i in range(1, len(close)):
        if close[i-1] > upperband[i-1]:
            lowerband[i] = max(lowerband[i], lowerband[i-1])
        if close[i-1] < lowerband[i-1]:
            upperband[i] = min(upperband[i], upperband[i-1])

        if close[i] > upperband[i-1]:
            direction[i] = 1
        elif close[i] < lowerband[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and lowerband[i] < lowerband[i-1]:
                lowerband[i] = lowerband[i-1]
            if direction[i] == -1 and upperband[i] > upperband[i-1]:
                upperband[i] = upperband[i-1]

        supertrend[i] = lowerband[i] if direction[i] == 1 else upperband[i]

    return direction, supertrend


class SupertrendIntraday(Strategy):
    """Trades in the direction of Supertrend with trailing stop."""
    st_period = 10
    st_mult = 2.5
    sl_pct = 0.008
    tp_pct = 0.016

    def init(self):
        st_dir, st_val = calc_supertrend(self.data.df, self.st_period, self.st_mult)
        self.st_dir = self.I(lambda: st_dir)
        self.st_val = self.I(lambda: st_val)
        self._current_date = None
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._traded_today = False

        if bar_time_mins >= 915:
            if self.position:
                self.position.close()
            return

        if bar_time_mins < 570 or bar_time_mins > 780 or self._traded_today or self.position:
            return

        price = self.data.Close[-1]
        prev_dir = self.st_dir[-2]
        curr_dir = self.st_dir[-1]

        # Bullish flip
        if prev_dir != 1 and curr_dir == 1:
            self._traded_today = True
            sl = price * (1.0 - self.sl_pct)
            tp = price * (1.0 + self.tp_pct)
            self.buy(sl=sl, tp=tp)
            return

        # Bearish flip
        if prev_dir != -1 and curr_dir == -1:
            self._traded_today = True
            sl = price * (1.0 + self.sl_pct)
            tp = price * (1.0 - self.tp_pct)
            self.sell(sl=sl, tp=tp)
            return


# -------------------------------------------------------------
# Strategy C: 15-Minute EMA 9/21 Momentum Crossover
# -------------------------------------------------------------
class EMAMomentumIntraday(Strategy):
    ema_fast = 9
    ema_slow = 21
    sl_pct = 0.007
    tp_pct = 0.015

    def init(self):
        def calc_ema(s, n):
            return pd.Series(s).ewm(span=n, adjust=False).mean().values
        self.fast = self.I(calc_ema, self.data.Close, self.ema_fast)
        self.slow = self.I(calc_ema, self.data.Close, self.ema_slow)
        self.ema200 = self.I(calc_ema, self.data.Close, 100)
        self._current_date = None
        self._traded_today = False

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._traded_today = False

        if bar_time_mins >= 915:
            if self.position:
                self.position.close()
            return

        if bar_time_mins < 570 or bar_time_mins > 780 or self._traded_today or self.position:
            return

        price = self.data.Close[-1]
        fast = self.fast
        slow = self.slow

        # Golden cross + trend filter
        if fast[-2] <= slow[-2] and fast[-1] > slow[-1] and price > self.ema200[-1]:
            self._traded_today = True
            sl = price * (1.0 - self.sl_pct)
            tp = price * (1.0 + self.tp_pct)
            self.buy(sl=sl, tp=tp)
            return

        # Death cross + trend filter
        if fast[-2] >= slow[-2] and fast[-1] < slow[-1] and price < self.ema200[-1]:
            self._traded_today = True
            sl = price * (1.0 + self.sl_pct)
            tp = price * (1.0 - self.tp_pct)
            self.sell(sl=sl, tp=tp)
            return


# -------------------------------------------------------------
# Evaluate All
# -------------------------------------------------------------
def run_evaluation(name, strat_cls):
    print(f"\n{'='*75}")
    print(f"  STRATEGY: {name}")
    print(f"{'='*75}")
    res = []
    for sym in STOCKS:
        data = load_data(f"data/{sym}_5min.csv")
        bt = Backtest(data, strat_cls, cash=100_000, commission=COMMISSION,
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
        res.append({"return": ret, "sharpe": sharpe, "trades": trades, "win_rate": wr})

    df = pd.DataFrame(res)
    print(f"  --> Average Return: {df['return'].mean():+.2f}%, Avg Sharpe: {df['sharpe'].mean():.3f}, Avg Trades: {df['trades'].mean():.0f}")


if __name__ == "__main__":
    run_evaluation("1. Candidate C: Gap + ORB Continuation (min gap 0.5%)", GapORBContinuation)
    run_evaluation("2. Supertrend Intraday Trend Following", SupertrendIntraday)
    run_evaluation("3. EMA 9/21 Trend Crossover + 100 EMA Filter", EMAMomentumIntraday)
