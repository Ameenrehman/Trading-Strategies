"""
High-Performance Backtesting Engine for 8/13 EMA Pullback Strategy on Indian Equities Intraday.

Runs bar-by-bar across all 50 Nifty constituents with zero look-ahead bias,
realistic execution mechanics (resting breakout stops, 5 bps slippage,
worst-case same-candle SL/TP resolution), exact 2026 statutory costs,
and fixed-fractional risk sizing.
"""

import os
import sys
import glob
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.ema_pullback import (
    PullbackType,
    StopLossType,
    TradeManagementMode,
    StrategyConfig,
    compute_ema,
    compute_atr,
    is_valid_pullback,
)
from strategies.session import session_arrays
from backtest.costs import round_trip_cost

# In-memory global data cache to avoid re-reading 50 CSVs from disk on every grid variation
DATA_CACHE: Dict[str, Dict[str, Any]] = {}


def preload_universe_data(data_dir: str = "data/intraday_5min") -> Dict[str, Dict[str, Any]]:
    """Preload all 50 CSV files into memory once with precomputed session arrays."""
    global DATA_CACHE
    if DATA_CACHE:
        return DATA_CACHE

    csv_files = glob.glob(os.path.join(data_dir, "*.csv"))
    print(f"Preloading {len(csv_files)} stock datasets into memory...", flush=True)

    for f in csv_files:
        sym = os.path.basename(f).replace("_5min.csv", "")
        df = pd.read_csv(f)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.sort_values("datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)

        dt_index = pd.DatetimeIndex(df["datetime"])
        s_arr = session_arrays(dt_index)

        DATA_CACHE[sym] = {
            "symbol": sym,
            "dt_index": dt_index,
            "tod": s_arr["tod"],
            "day_id": s_arr["day_id"],
            "is_first_bar": s_arr["is_first_bar"],
            "is_last_bar": s_arr["is_last_bar"],
            "open": df["open"].to_numpy(dtype=float),
            "high": df["high"].to_numpy(dtype=float),
            "low": df["low"].to_numpy(dtype=float),
            "close": df["close"].to_numpy(dtype=float),
            "volume": df["volume"].to_numpy(dtype=float),
        }

    print(f"Preloaded {len(DATA_CACHE)} stocks successfully.", flush=True)
    return DATA_CACHE


def run_ema_pullback_single_stock(
    stock_data: Dict[str, Any],
    config: StrategyConfig,
    initial_equity: float = 100_000.0,
) -> List[Dict[str, Any]]:
    """
    Simulate the EMA Pullback Strategy on preloaded stock data.
    """
    symbol = stock_data["symbol"]
    dt_index = stock_data["dt_index"]
    tod = stock_data["tod"]
    day_id = stock_data["day_id"]
    is_first_bar = stock_data["is_first_bar"]
    is_last_bar = stock_data["is_last_bar"]
    open_p = stock_data["open"]
    high_p = stock_data["high"]
    low_p = stock_data["low"]
    close_p = stock_data["close"]

    n = len(close_p)
    if n < config.slow_ema + 20:
        return []

    fast_ema = compute_ema(close_p, config.fast_ema)
    slow_ema = compute_ema(close_p, config.slow_ema)
    atr = compute_atr(high_p, low_p, close_p, is_first_bar, config.atr_period)

    # Slippage fraction
    slip = config.slippage_bps / 10_000.0
    trades: List[Dict[str, Any]] = []

    # State variables
    current_bias = 0  # +1 Bullish, -1 Bearish
    pending_setup = None  # Dict with setup details
    position = None  # Dict with active position details
    current_equity = initial_equity

    for i in range(1, n):
        cur_tod = tod[i]
        bar_dt = dt_index[i]

        # 1. Update EMA crossover bias
        if fast_ema[i - 1] <= slow_ema[i - 1] and fast_ema[i] > slow_ema[i]:
            current_bias = 1
            if pending_setup and pending_setup["direction"] == -1:
                pending_setup = None
        elif fast_ema[i - 1] >= slow_ema[i - 1] and fast_ema[i] < slow_ema[i]:
            current_bias = -1
            if pending_setup and pending_setup["direction"] == 1:
                pending_setup = None

        # Reset pending setup on day change
        if is_first_bar[i]:
            pending_setup = None

        # 2. Manage Open Position if any
        if position is not None:
            pos_dir = position["direction"]
            entry_price = position["entry_price"]
            sl_price = position["current_sl"]
            risk_dist = position["risk_dist"]
            pos_mode = config.management_mode
            partial_exited = position["partial_exited"]

            # Determine target levels
            if pos_mode in (TradeManagementMode.A_FULL_1_2, TradeManagementMode.C_PARTIAL_1_2):
                final_target = entry_price + (2.0 * risk_dist if pos_dir == 1 else -2.0 * risk_dist)
            elif pos_mode in (TradeManagementMode.B_FULL_1_3, TradeManagementMode.D_PARTIAL_1_3):
                final_target = entry_price + (3.0 * risk_dist if pos_dir == 1 else -3.0 * risk_dist)
            else:  # Fixed RR
                final_target = entry_price + (config.fixed_rr * risk_dist if pos_dir == 1 else -config.fixed_rr * risk_dist)

            target_1r = entry_price + (1.0 * risk_dist if pos_dir == 1 else -1.0 * risk_dist)

            # Check intraday mandatory square-off
            is_eod = (cur_tod >= config.square_off_time) or is_last_bar[i]

            if is_eod:
                exit_price = close_p[i] * (1.0 - slip if pos_dir == 1 else 1.0 + slip)
                position["legs"].append({
                    "time": bar_dt,
                    "shares": position["remaining_shares"],
                    "price": exit_price,
                    "reason": "EOD_Squareoff"
                })
                trade_record = _finalize_trade(position, symbol, config)
                trades.append(trade_record)
                current_equity += trade_record["net_pnl"]
                position = None

            elif pos_dir == 1:  # LONG POSITION
                # Check 1R partial target
                if not partial_exited and pos_mode in (
                    TradeManagementMode.C_PARTIAL_1_2,
                    TradeManagementMode.D_PARTIAL_1_3,
                    TradeManagementMode.E_PARTIAL_TRAIL
                ):
                    if high_p[i] >= target_1r:
                        half_shares = position["remaining_shares"] // 2
                        if half_shares > 0:
                            position["legs"].append({
                                "time": bar_dt,
                                "shares": half_shares,
                                "price": target_1r,
                                "reason": "1R_Partial_TP"
                            })
                            position["remaining_shares"] -= half_shares
                            position["partial_exited"] = True
                            position["current_sl"] = max(position["current_sl"], entry_price)
                            sl_price = position["current_sl"]

                if partial_exited and pos_mode == TradeManagementMode.E_PARTIAL_TRAIL:
                    position["current_sl"] = max(position["current_sl"], slow_ema[i])
                    sl_price = position["current_sl"]

                # Check SL and Final Target on current bar
                hit_sl = low_p[i] <= sl_price
                hit_tp = high_p[i] >= final_target

                if hit_sl and hit_tp:
                    # CONSERVATIVE WORST-CASE: SL hit first
                    exit_price = sl_price * (1.0 - slip)
                    position["legs"].append({
                        "time": bar_dt,
                        "shares": position["remaining_shares"],
                        "price": exit_price,
                        "reason": "Stop_Loss_Conflict"
                    })
                    trade_record = _finalize_trade(position, symbol, config)
                    trades.append(trade_record)
                    current_equity += trade_record["net_pnl"]
                    position = None

                elif hit_sl:
                    exit_price = sl_price * (1.0 - slip)
                    position["legs"].append({
                        "time": bar_dt,
                        "shares": position["remaining_shares"],
                        "price": exit_price,
                        "reason": "Stop_Loss"
                    })
                    trade_record = _finalize_trade(position, symbol, config)
                    trades.append(trade_record)
                    current_equity += trade_record["net_pnl"]
                    position = None

                elif hit_tp and (pos_mode != TradeManagementMode.E_PARTIAL_TRAIL or not partial_exited):
                    exit_price = final_target
                    position["legs"].append({
                        "time": bar_dt,
                        "shares": position["remaining_shares"],
                        "price": exit_price,
                        "reason": "Take_Profit"
                    })
                    trade_record = _finalize_trade(position, symbol, config)
                    trades.append(trade_record)
                    current_equity += trade_record["net_pnl"]
                    position = None

            elif pos_dir == -1:  # SHORT POSITION
                # Check 1R partial target
                if not partial_exited and pos_mode in (
                    TradeManagementMode.C_PARTIAL_1_2,
                    TradeManagementMode.D_PARTIAL_1_3,
                    TradeManagementMode.E_PARTIAL_TRAIL
                ):
                    if low_p[i] <= target_1r:
                        half_shares = position["remaining_shares"] // 2
                        if half_shares > 0:
                            position["legs"].append({
                                "time": bar_dt,
                                "shares": half_shares,
                                "price": target_1r,
                                "reason": "1R_Partial_TP"
                            })
                            position["remaining_shares"] -= half_shares
                            position["partial_exited"] = True
                            position["current_sl"] = min(position["current_sl"], entry_price)
                            sl_price = position["current_sl"]

                if partial_exited and pos_mode == TradeManagementMode.E_PARTIAL_TRAIL:
                    position["current_sl"] = min(position["current_sl"], slow_ema[i])
                    sl_price = position["current_sl"]

                hit_sl = high_p[i] >= sl_price
                hit_tp = low_p[i] <= final_target

                if hit_sl and hit_tp:
                    # CONSERVATIVE WORST-CASE: SL hit first
                    exit_price = sl_price * (1.0 + slip)
                    position["legs"].append({
                        "time": bar_dt,
                        "shares": position["remaining_shares"],
                        "price": exit_price,
                        "reason": "Stop_Loss_Conflict"
                    })
                    trade_record = _finalize_trade(position, symbol, config)
                    trades.append(trade_record)
                    current_equity += trade_record["net_pnl"]
                    position = None

                elif hit_sl:
                    exit_price = sl_price * (1.0 + slip)
                    position["legs"].append({
                        "time": bar_dt,
                        "shares": position["remaining_shares"],
                        "price": exit_price,
                        "reason": "Stop_Loss"
                    })
                    trade_record = _finalize_trade(position, symbol, config)
                    trades.append(trade_record)
                    current_equity += trade_record["net_pnl"]
                    position = None

                elif hit_tp and (pos_mode != TradeManagementMode.E_PARTIAL_TRAIL or not partial_exited):
                    exit_price = final_target
                    position["legs"].append({
                        "time": bar_dt,
                        "shares": position["remaining_shares"],
                        "price": exit_price,
                        "reason": "Take_Profit"
                    })
                    trade_record = _finalize_trade(position, symbol, config)
                    trades.append(trade_record)
                    current_equity += trade_record["net_pnl"]
                    position = None

        # 3. Check Pending Breakout Setup (if no position)
        if position is None and pending_setup is not None:
            setup_dir = pending_setup["direction"]
            setup_mark = pending_setup["mark_price"]
            setup_sl = pending_setup["sl_price"]
            setup_bar_age = i - pending_setup["bar_idx"]

            if setup_bar_age > config.max_setup_bars or cur_tod > config.max_entry_time or cur_tod < config.min_entry_time:
                pending_setup = None
            else:
                triggered = False
                fill_price = 0.0

                if setup_dir == 1 and config.allow_long:
                    if high_p[i] >= setup_mark:
                        fill_price = max(setup_mark, open_p[i]) * (1.0 + slip)
                        triggered = True
                elif setup_dir == -1 and config.allow_short:
                    if low_p[i] <= setup_mark:
                        fill_price = min(setup_mark, open_p[i]) * (1.0 - slip)
                        triggered = True

                if triggered:
                    risk_dist = abs(fill_price - setup_sl)
                    if risk_dist > 0:
                        risk_capital = current_equity * config.risk_pct
                        shares = int(risk_capital / risk_dist)
                        max_shares = int((current_equity * config.max_leverage) / fill_price)
                        shares = min(shares, max_shares)

                        if shares > 0:
                            position = {
                                "symbol": symbol,
                                "direction": setup_dir,
                                "entry_time": bar_dt,
                                "entry_price": fill_price,
                                "initial_sl": setup_sl,
                                "current_sl": setup_sl,
                                "risk_dist": risk_dist,
                                "initial_risk_capital": risk_dist * shares,
                                "shares": shares,
                                "remaining_shares": shares,
                                "partial_exited": False,
                                "legs": [],
                                "pullback_type": pending_setup["pullback_type"],
                                "atr_at_entry": atr[i],
                                "candle_size": pending_setup["candle_size"],
                                "pullback_depth_pct": pending_setup["pullback_depth_pct"],
                            }
                    pending_setup = None

        # 4. Detect New Pullback Setup (if no position and inside entry window)
        if position is None and config.min_entry_time <= cur_tod <= config.max_entry_time:
            if current_bias != 0:
                is_pb = is_valid_pullback(
                    direction=current_bias,
                    open_p=open_p[i],
                    high_p=high_p[i],
                    low_p=low_p[i],
                    close_p=close_p[i],
                    fast_ema=fast_ema[i],
                    slow_ema=slow_ema[i],
                    pullback_type=config.pullback_type,
                )
                if is_pb:
                    if current_bias == 1:
                        mark_price = high_p[i]
                        candle_size = high_p[i] - low_p[i]
                        depth_pct = (fast_ema[i] - low_p[i]) / fast_ema[i] if fast_ema[i] > 0 else 0

                        if config.stop_loss_type == StopLossType.PULLBACK_EXTREME:
                            sl_price = low_p[i]
                        elif config.stop_loss_type == StopLossType.EXTREME_BUFFER_PCT:
                            sl_price = low_p[i] * (1.0 - config.buffer_pct)
                        elif config.stop_loss_type == StopLossType.EXTREME_BUFFER_ATR:
                            sl_price = low_p[i] - (config.buffer_atr_mult * atr[i])
                        elif config.stop_loss_type == StopLossType.SLOW_EMA:
                            sl_price = min(low_p[i], slow_ema[i])
                        else:
                            sl_price = low_p[i]

                    else:  # current_bias == -1
                        mark_price = low_p[i]
                        candle_size = high_p[i] - low_p[i]
                        depth_pct = (high_p[i] - fast_ema[i]) / fast_ema[i] if fast_ema[i] > 0 else 0

                        if config.stop_loss_type == StopLossType.PULLBACK_EXTREME:
                            sl_price = high_p[i]
                        elif config.stop_loss_type == StopLossType.EXTREME_BUFFER_PCT:
                            sl_price = high_p[i] * (1.0 + config.buffer_pct)
                        elif config.stop_loss_type == StopLossType.EXTREME_BUFFER_ATR:
                            sl_price = high_p[i] + (config.buffer_atr_mult * atr[i])
                        elif config.stop_loss_type == StopLossType.SLOW_EMA:
                            sl_price = max(high_p[i], slow_ema[i])
                        else:
                            sl_price = high_p[i]

                    pending_setup = {
                        "direction": current_bias,
                        "bar_idx": i,
                        "mark_price": mark_price,
                        "sl_price": sl_price,
                        "pullback_type": config.pullback_type.value,
                        "candle_size": candle_size,
                        "pullback_depth_pct": depth_pct,
                    }

    return trades


def _finalize_trade(position: Dict[str, Any], symbol: str, config: StrategyConfig) -> Dict[str, Any]:
    """Calculate exact statutory costs, Gross/Net PnL, R-multiple, and metrics."""
    pos_dir = position["direction"]
    entry_price = position["entry_price"]
    total_shares = position["shares"]
    entry_val = entry_price * total_shares
    initial_risk = position["initial_risk_capital"]

    gross_pnl = 0.0
    total_cost = 0.0
    exit_times = []
    exit_reasons = []

    for leg in position["legs"]:
        leg_shares = leg["shares"]
        leg_price = leg["price"]

        if pos_dir == 1:
            leg_gross = (leg_price - entry_price) * leg_shares
        else:
            leg_gross = (entry_price - leg_price) * leg_shares
        gross_pnl += leg_gross

        buy_val = (entry_price if pos_dir == 1 else leg_price) * leg_shares
        sell_val = (leg_price if pos_dir == 1 else entry_price) * leg_shares
        cost_dict = round_trip_cost(buy_val, sell_val)
        total_cost += cost_dict["total"]

        exit_times.append(leg["time"])
        exit_reasons.append(leg["reason"])

    net_pnl = gross_pnl - total_cost
    r_multiple = (net_pnl / initial_risk) if initial_risk > 0 else 0.0
    gross_bps = (gross_pnl / entry_val) * 10_000 if entry_val > 0 else 0.0
    net_bps = (net_pnl / entry_val) * 10_000 if entry_val > 0 else 0.0
    cost_bps = (total_cost / entry_val) * 10_000 if entry_val > 0 else 0.0

    last_exit_time = exit_times[-1] if exit_times else position["entry_time"]
    duration_mins = (last_exit_time - position["entry_time"]).total_seconds() / 60.0

    return {
        "symbol": symbol,
        "direction": "LONG" if pos_dir == 1 else "SHORT",
        "entry_time": position["entry_time"],
        "exit_time": last_exit_time,
        "entry_price": entry_price,
        "shares": total_shares,
        "entry_value": entry_val,
        "gross_pnl": gross_pnl,
        "cost": total_cost,
        "net_pnl": net_pnl,
        "gross_bps": gross_bps,
        "cost_bps": cost_bps,
        "net_bps": net_bps,
        "r_multiple": r_multiple,
        "win": 1 if net_pnl > 0 else 0,
        "exit_reasons": ",".join(exit_reasons),
        "duration_mins": duration_mins,
        "atr_at_entry": position["atr_at_entry"],
        "candle_size": position["candle_size"],
        "pullback_depth_pct": position["pullback_depth_pct"],
        "pullback_type": position["pullback_type"],
    }


def run_ema_pullback_universe(
    config: Optional[StrategyConfig] = None,
    symbols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Run EMA Pullback strategy across preloaded universe data in memory."""
    global DATA_CACHE
    if not DATA_CACHE:
        preload_universe_data()

    if config is None:
        config = StrategyConfig()

    stock_items = list(DATA_CACHE.values())
    if symbols:
        stock_items = [item for item in stock_items if item["symbol"] in symbols]

    all_trades: List[Dict[str, Any]] = []

    for item in stock_items:
        trades = run_ema_pullback_single_stock(item, config)
        all_trades.extend(trades)

    if not all_trades:
        return pd.DataFrame()

    trades_df = pd.DataFrame(all_trades)
    trades_df.sort_values("entry_time", inplace=True)
    trades_df.reset_index(drop=True, inplace=True)
    return trades_df


if __name__ == "__main__":
    preload_universe_data()
    print("Running Baseline 8/13 EMA Pullback on 50 Nifty Constituents...", flush=True)
    cfg = StrategyConfig(
        fast_ema=8,
        slow_ema=13,
        pullback_type=PullbackType.ZONE,
        stop_loss_type=StopLossType.PULLBACK_EXTREME,
        fixed_rr=2.0,
        management_mode=TradeManagementMode.A_FULL_1_2,
    )
    df_trades = run_ema_pullback_universe(config=cfg)
    print(f"Total Trades Generated: {len(df_trades):,}", flush=True)
    if not df_trades.empty:
        win_rate = df_trades["win"].mean() * 100
        gross_mean_bps = df_trades["gross_bps"].mean()
        net_mean_bps = df_trades["net_bps"].mean()
        cost_mean_bps = df_trades["cost_bps"].mean()
        avg_r = df_trades["r_multiple"].mean()
        t_stat = (df_trades["net_bps"].mean() / (df_trades["net_bps"].std() / np.sqrt(len(df_trades)))) if len(df_trades) > 1 else 0

        print(f"Win Rate: {win_rate:.2f}%", flush=True)
        print(f"Gross Edge: {gross_mean_bps:+.2f} bps/trade", flush=True)
        print(f"Statutory Cost: {cost_mean_bps:.2f} bps/trade", flush=True)
        print(f"Net Edge: {net_mean_bps:+.2f} bps/trade (t-stat = {t_stat:.2f})", flush=True)
        print(f"Average Expectancy: {avg_r:+.3f} R/trade", flush=True)
