"""
Systematic Strategy Explorer: Test multiple strategies & filters across the 5 Nifty 50 stocks.

We test:
1. ORB + Trend Filter (EMA 50/200)
2. ORB + Volume Expansion (> 1.5x SMA)
3. ORB + Gap Filter (Candidate C: Gap open continuation)
4. ORB + ATR Trailing Stop / Tighter SL
5. VWAP Strategy (Candidate B: Price crossover with VWAP)
6. Mean Reversion (Fade opening false breakouts / Bollinger bands)
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


# -------------------------------------------------------------
# Indicator Helpers
# -------------------------------------------------------------
def calc_ema(series, length):
    return pd.Series(series).ewm(span=length, adjust=False).mean().values

def calc_sma(series, length):
    return pd.Series(series).rolling(length, min_periods=1).mean().values

def calc_intraday_vwap(df):
    """Calculate cumulative intraday VWAP resetting each morning at 9:15."""
    df_temp = df.copy()
    df_temp['date'] = df_temp.index.date
    df_temp['pv'] = ((df_temp['High'] + df_temp['Low'] + df_temp['Close']) / 3.0) * df_temp['Volume']
    cum_pv = df_temp.groupby('date')['pv'].cumsum()
    cum_vol = df_temp.groupby('date')['Volume'].cumsum()
    vwap = cum_pv / np.maximum(cum_vol, 1)
    return vwap.values


# -------------------------------------------------------------
# Strategy 1: Trend & Volume Filtered ORB
# -------------------------------------------------------------
class FilteredORBStrategy(Strategy):
    or_bars = 6
    rr_ratio = 2.0
    vol_mult = 1.2
    max_entry_time = 720  # 12:00 PM

    def init(self):
        self.ema50 = self.I(calc_ema, self.data.Close, 50)
        self.ema200 = self.I(calc_ema, self.data.Close, 200)
        self.vol_sma = self.I(calc_sma, self.data.Volume, 20)
        
        self._range_high = np.nan
        self._range_low = np.nan
        self._bar_count = 0
        self._traded_today = False
        self._current_date = None

    def next(self):
        bar_time = self.data.index[-1]
        bar_date = bar_time.date() if hasattr(bar_time, 'date') else bar_time
        bar_time_mins = (bar_time.hour if hasattr(bar_time, 'hour') else 0) * 60 + (bar_time.minute if hasattr(bar_time, 'minute') else 0)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._bar_count = 0
            self._range_high = -np.inf
            self._range_low = np.inf
            self._traded_today = False

        self._bar_count += 1

        if self._bar_count <= self.or_bars:
            self._range_high = max(self._range_high, self.data.High[-1])
            self._range_low = min(self._range_low, self.data.Low[-1])
            return

        if bar_time_mins >= 915:
            if self.position:
                self.position.close()
            return

        if bar_time_mins > self.max_entry_time or self._traded_today or self.position:
            return

        range_size = self._range_high - self._range_low
        if range_size <= 0:
            return

        price = self.data.Close[-1]
        vol = self.data.Volume[-1]
        vol_avg = self.vol_sma[-1]
        has_volume = vol > (vol_avg * self.vol_mult)

        # Long: Breakout + Price > EMA50 > EMA200 + Volume confirmation
        if price > self._range_high and price > self.ema50[-1] > self.ema200[-1] and has_volume:
            self._traded_today = True
            risk = range_size
            sl = max(self._range_low, price - risk)
            tp = price + (risk * self.rr_ratio)
            if sl < price < tp:
                self.buy(sl=sl, tp=tp)
            return

        # Short: Breakout + Price < EMA50 < EMA200 + Volume confirmation
        if price < self._range_low and price < self.ema50[-1] < self.ema200[-1] and has_volume:
            self._traded_today = True
            risk = range_size
            sl = min(self._range_high, price + risk)
            tp = price - (risk * self.rr_ratio)
            if tp < price < sl:
                self.sell(sl=sl, tp=tp)
            return


# -------------------------------------------------------------
# Strategy 2: Candidate B — Intraday VWAP Breakout with Trend
# -------------------------------------------------------------
class VWAPBreakoutStrategy(Strategy):
    ema_fast = 20
    ema_slow = 50
    sl_pct = 0.007  # 0.7% SL
    tp_pct = 0.014  # 1.4% TP (2:1 RR)

    def init(self):
        # We compute VWAP beforehand or pass it
        self.ema_f = self.I(calc_ema, self.data.Close, self.ema_fast)
        self.ema_s = self.I(calc_ema, self.data.Close, self.ema_slow)
        self.vwap = self.I(lambda: self.data.df['vwap'].values)

        self._traded_today = False
        self._current_date = None

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

        # Skip first 15 mins (let VWAP stabilize) and no entries after 1:00 PM (780 mins)
        if bar_time_mins < 570 or bar_time_mins > 780 or self._traded_today or self.position:
            return

        price = self.data.Close[-1]
        prev_price = self.data.Close[-2]
        vwap = self.vwap[-1]
        prev_vwap = self.vwap[-2]

        # Bullish: Crosses above VWAP + EMA fast > EMA slow
        if prev_price <= prev_vwap and price > vwap and self.ema_f[-1] > self.ema_s[-1]:
            self._traded_today = True
            sl = price * (1.0 - self.sl_pct)
            tp = price * (1.0 + self.tp_pct)
            self.buy(sl=sl, tp=tp)
            return

        # Bearish: Crosses below VWAP + EMA fast < EMA slow
        if prev_price >= prev_vwap and price < vwap and self.ema_f[-1] < self.ema_s[-1]:
            self._traded_today = True
            sl = price * (1.0 + self.sl_pct)
            tp = price * (1.0 - self.tp_pct)
            self.sell(sl=sl, tp=tp)
            return


# -------------------------------------------------------------
# Strategy 3: Mean Reversion / VWAP Pullback Strategy
# -------------------------------------------------------------
class VWAPPullbackStrategy(Strategy):
    """Buy oversold pullbacks to VWAP in uptrend; sell overbought in downtrend."""
    rsi_period = 14
    sl_pct = 0.006
    tp_pct = 0.012

    def init(self):
        # RSI
        def calc_rsi(close, period=14):
            delta = pd.Series(close).diff()
            gain = (delta.where(delta > 0, 0)).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            rs = gain / np.maximum(loss, 1e-9)
            return (100 - (100 / (1 + rs))).values

        self.rsi = self.I(calc_rsi, self.data.Close, self.rsi_period)
        self.ema50 = self.I(calc_ema, self.data.Close, 50)
        self.vwap = self.I(lambda: self.data.df['vwap'].values)

        self._traded_today = False
        self._current_date = None

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

        if bar_time_mins < 570 or bar_time_mins > 800 or self._traded_today or self.position:
            return

        price = self.data.Close[-1]
        vwap = self.vwap[-1]
        rsi = self.rsi[-1]

        # Uptrend pullback: Price near VWAP (within 0.3%), RSI < 45, EMA50 trending up
        if price > self.ema50[-1] and abs(price - vwap) / price < 0.003 and rsi < 45:
            self._traded_today = True
            sl = price * (1.0 - self.sl_pct)
            tp = price * (1.0 + self.tp_pct)
            self.buy(sl=sl, tp=tp)
            return

        # Downtrend pullback: Price near VWAP, RSI > 55, EMA50 trending down
        if price < self.ema50[-1] and abs(price - vwap) / price < 0.003 and rsi > 55:
            self._traded_today = True
            sl = price * (1.0 + self.sl_pct)
            tp = price * (1.0 - self.tp_pct)
            self.sell(sl=sl, tp=tp)
            return


# -------------------------------------------------------------
# Runner & Comparison
# -------------------------------------------------------------
def evaluate_strategy(name, strategy_cls, extra_cols=False):
    print(f"\n{'='*75}")
    print(f"  STRATEGY EVALUATION: {name}")
    print(f"{'='*75}")
    results = []

    for sym in STOCKS:
        data = load_data(f"data/intraday_5min/{sym}_5min.csv")
        if extra_cols:
            data['vwap'] = calc_intraday_vwap(data)

        bt = Backtest(data, strategy_cls, cash=100_000, commission=COMMISSION,
                      exclusive_orders=True, trade_on_close=True)
        stats = bt.run()
        ret = stats.get("Return [%]", 0)
        win_rate = stats.get("Win Rate [%]", 0)
        trades = stats.get("# Trades", 0)
        pf = stats.get("Profit Factor", 0)
        sharpe = stats.get("Sharpe Ratio", 0)
        max_dd = stats.get("Max. Drawdown [%]", 0)

        results.append({
            "symbol": sym,
            "return": ret,
            "win_rate": win_rate,
            "trades": trades,
            "profit_factor": pf,
            "sharpe": sharpe,
            "max_dd": max_dd
        })

        pf_str = f"{pf:.3f}" if pf else "N/A"
        print(f"  {sym:10s} | Return: {ret:+6.2f}% | WinRate: {win_rate:4.1f}% | Trades: {trades:3d} | PF: {pf_str} | Sharpe: {sharpe:+6.3f} | MaxDD: {max_dd:5.2f}%")

    df_res = pd.DataFrame(results)
    avg_ret = df_res["return"].mean()
    avg_sharpe = df_res["sharpe"].mean()
    print(f"  --> Average Return: {avg_ret:+.2f}%, Avg Sharpe: {avg_sharpe:.3f}")
    return df_res


if __name__ == "__main__":
    print("Testing Strategy Candidates on 2-Year Intraday NSE Large-Caps...")
    evaluate_strategy("1. Trend + Volume Filtered ORB", FilteredORBStrategy)
    evaluate_strategy("2. Candidate B: Intraday VWAP Breakout", VWAPBreakoutStrategy, extra_cols=True)
    evaluate_strategy("3. Mean Reversion: VWAP Pullback", VWAPPullbackStrategy, extra_cols=True)
