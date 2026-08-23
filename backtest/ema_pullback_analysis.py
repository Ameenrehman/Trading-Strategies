"""
Comprehensive Analysis, Optimization, Robustness, and Monte Carlo Suite
for 8/13 EMA Pullback Strategy on Indian Stocks Intraday.

Produces all statistical metrics, parameter grids, trade management evaluations,
robustness splits, Monte Carlo simulations, and visual chart artifacts.
"""

import os
import sys
import json
import glob
from pathlib import Path
from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.ema_pullback import (
    PullbackType,
    StopLossType,
    TradeManagementMode,
    StrategyConfig,
)
from backtest.test_ema_pullback import (
    preload_universe_data,
    run_ema_pullback_universe,
)

RESULTS_DIR = PROJECT_ROOT / "backtest" / "results" / "ema_pullback"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def calculate_metrics(trades_df: pd.DataFrame, initial_capital: float = 100_000.0) -> Dict[str, Any]:
    """Calculate comprehensive institutional-grade trading metrics."""
    if trades_df.empty or len(trades_df) == 0:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "gross_bps": 0.0,
            "net_bps": 0.0,
            "cost_bps": 0.0,
            "avg_r": 0.0,
            "profit_factor": 0.0,
            "net_pnl": 0.0,
            "max_dd_pct": 0.0,
            "max_dd_rupees": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "t_stat": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "max_win_r": 0.0,
            "max_loss_r": 0.0,
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "avg_duration_mins": 0.0,
        }

    n_trades = len(trades_df)
    net_pnls = trades_df["net_pnl"].to_numpy()
    gross_pnls = trades_df["gross_pnl"].to_numpy()
    r_mults = trades_df["r_multiple"].to_numpy()
    net_bps_arr = trades_df["net_bps"].to_numpy()
    gross_bps_arr = trades_df["gross_bps"].to_numpy()
    cost_bps_arr = trades_df["cost_bps"].to_numpy()

    wins = trades_df[trades_df["net_pnl"] > 0]
    losses = trades_df[trades_df["net_pnl"] <= 0]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / n_trades) * 100.0

    total_gross_gain = wins["gross_pnl"].sum()
    total_gross_loss = abs(losses["gross_pnl"].sum())
    profit_factor = (total_gross_gain / total_gross_loss) if total_gross_loss > 0 else (99.0 if total_gross_gain > 0 else 0.0)

    # Equity and Drawdown
    equity_curve = initial_capital + np.cumsum(net_pnls)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = (equity_curve - peak) / peak * 100.0
    dd_rupees = equity_curve - peak
    max_dd_pct = abs(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
    max_dd_rupees = abs(np.min(dd_rupees)) if len(dd_rupees) > 0 else 0.0

    # Sharpe & Sortino
    mean_net_bps = np.mean(net_bps_arr)
    std_net_bps = np.std(net_bps_arr, ddof=1) if n_trades > 1 else 1e-6
    t_stat = (mean_net_bps / (std_net_bps / np.sqrt(n_trades))) if std_net_bps > 0 else 0.0

    trades_per_year = n_trades / 2.0
    annual_factor = np.sqrt(trades_per_year) if trades_per_year > 0 else 1.0
    sharpe = (mean_net_bps / std_net_bps) * annual_factor if std_net_bps > 0 else 0.0

    downside_returns = net_bps_arr[net_bps_arr < 0]
    downside_std = np.std(downside_returns, ddof=1) if len(downside_returns) > 1 else std_net_bps
    sortino = (mean_net_bps / downside_std) * annual_factor if downside_std > 0 else 0.0

    # Streaks
    is_win = (net_pnls > 0).astype(int)
    max_win_streak = 0
    max_loss_streak = 0
    cur_win = 0
    cur_loss = 0
    for w in is_win:
        if w == 1:
            cur_win += 1
            cur_loss = 0
            if cur_win > max_win_streak:
                max_win_streak = cur_win
        else:
            cur_loss += 1
            cur_win = 0
            if cur_loss > max_loss_streak:
                max_loss_streak = cur_loss

    return {
        "total_trades": n_trades,
        "win_rate": win_rate,
        "gross_bps": float(np.mean(gross_bps_arr)),
        "cost_bps": float(np.mean(cost_bps_arr)),
        "net_bps": float(mean_net_bps),
        "avg_r": float(np.mean(r_mults)),
        "profit_factor": float(profit_factor),
        "net_pnl": float(np.sum(net_pnls)),
        "max_dd_pct": float(max_dd_pct),
        "max_dd_rupees": float(max_dd_rupees),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "t_stat": float(t_stat),
        "win_count": win_count,
        "loss_count": loss_count,
        "avg_win_r": float(wins["r_multiple"].mean()) if not wins.empty else 0.0,
        "avg_loss_r": float(losses["r_multiple"].mean()) if not losses.empty else 0.0,
        "max_win_r": float(r_mults.max()) if len(r_mults) > 0 else 0.0,
        "max_loss_r": float(r_mults.min()) if len(r_mults) > 0 else 0.0,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "avg_duration_mins": float(trades_df["duration_mins"].mean()) if "duration_mins" in trades_df else 0.0,
    }


def run_all_investigations():
    """Run all strategy variations, regimes, trade managements, and tests."""
    print("=" * 80, flush=True)
    print("STARTING DEEP 8/13 EMA PULLBACK ANALYSIS ON 50 NIFTY 50 STOCKS", flush=True)
    print("=" * 80, flush=True)

    preload_universe_data()

    # -------------------------------------------------------------
    # 1. BASELINE COMPARISON: 1:2 RR vs 1:3 RR (Strategy A vs B)
    # -------------------------------------------------------------
    print("\n--- 1. Testing Baseline Strategy A (1:2 RR) and Strategy B (1:3 RR) ---", flush=True)
    cfg_base_1_2 = StrategyConfig(
        fast_ema=8,
        slow_ema=13,
        pullback_type=PullbackType.ZONE,
        stop_loss_type=StopLossType.PULLBACK_EXTREME,
        fixed_rr=2.0,
        management_mode=TradeManagementMode.A_FULL_1_2,
    )
    df_base_1_2 = run_ema_pullback_universe(config=cfg_base_1_2)
    m_base_1_2 = calculate_metrics(df_base_1_2)
    df_base_1_2.to_csv(RESULTS_DIR / "trades_baseline_1_2.csv", index=False)

    cfg_base_1_3 = StrategyConfig(
        fast_ema=8,
        slow_ema=13,
        pullback_type=PullbackType.ZONE,
        stop_loss_type=StopLossType.PULLBACK_EXTREME,
        fixed_rr=3.0,
        management_mode=TradeManagementMode.B_FULL_1_3,
    )
    df_base_1_3 = run_ema_pullback_universe(config=cfg_base_1_3)
    m_base_1_3 = calculate_metrics(df_base_1_3)
    df_base_1_3.to_csv(RESULTS_DIR / "trades_baseline_1_3.csv", index=False)

    print(f"Strategy A (1:2 RR): {m_base_1_2['total_trades']:,} trades | Win: {m_base_1_2['win_rate']:.1f}% | Gross: {m_base_1_2['gross_bps']:+.2f} bps | Net: {m_base_1_2['net_bps']:+.2f} bps | Exp: {m_base_1_2['avg_r']:+.3f} R", flush=True)
    print(f"Strategy B (1:3 RR): {m_base_1_3['total_trades']:,} trades | Win: {m_base_1_3['win_rate']:.1f}% | Gross: {m_base_1_3['gross_bps']:+.2f} bps | Net: {m_base_1_3['net_bps']:+.2f} bps | Exp: {m_base_1_3['avg_r']:+.3f} R", flush=True)

    # -------------------------------------------------------------
    # 2. TRADE MANAGEMENT COMPARISON: Strategies A, B, C, D, E
    # -------------------------------------------------------------
    print("\n--- 2. Testing Trade Management Strategies (A through E) ---", flush=True)
    management_modes = [
        ("Strategy A (Full 1:2)", TradeManagementMode.A_FULL_1_2),
        ("Strategy B (Full 1:3)", TradeManagementMode.B_FULL_1_3),
        ("Strategy C (50% @ 1R + BE + 2R)", TradeManagementMode.C_PARTIAL_1_2),
        ("Strategy D (50% @ 1R + BE + 3R)", TradeManagementMode.D_PARTIAL_1_3),
        ("Strategy E (50% @ 1R + BE + Trail)", TradeManagementMode.E_PARTIAL_TRAIL),
    ]
    mgmt_results = []
    for label, mode in management_modes:
        cfg = StrategyConfig(
            fast_ema=8,
            slow_ema=13,
            pullback_type=PullbackType.ZONE,
            stop_loss_type=StopLossType.PULLBACK_EXTREME,
            management_mode=mode,
        )
        df_m = run_ema_pullback_universe(config=cfg)
        metrics = calculate_metrics(df_m)
        metrics["label"] = label
        mgmt_results.append(metrics)
        print(f"{label:<32}: Trades={metrics['total_trades']:<6} | Win={metrics['win_rate']:4.1f}% | Gross={metrics['gross_bps']:+6.2f} bps | Net={metrics['net_bps']:+6.2f} bps | Exp={metrics['avg_r']:+6.3f} R | PF={metrics['profit_factor']:.2f}", flush=True)

    # -------------------------------------------------------------
    # 3. PULLBACK DEFINITIONS COMPARISON
    # -------------------------------------------------------------
    print("\n--- 3. Testing 5 Pullback Definitions ---", flush=True)
    pb_types = [
        ("Touch 8 EMA", PullbackType.TOUCH_FAST),
        ("Touch 13 EMA", PullbackType.TOUCH_SLOW),
        ("EMA Zone", PullbackType.ZONE),
        ("Directional Close", PullbackType.DIRECTIONAL_CLOSE),
        ("Wick Rejection", PullbackType.WICK_REJECTION),
    ]
    pb_results = []
    for label, pb_type in pb_types:
        cfg = StrategyConfig(
            fast_ema=8,
            slow_ema=13,
            pullback_type=pb_type,
            stop_loss_type=StopLossType.PULLBACK_EXTREME,
            fixed_rr=2.0,
            management_mode=TradeManagementMode.A_FULL_1_2,
        )
        df_pb = run_ema_pullback_universe(config=cfg)
        metrics = calculate_metrics(df_pb)
        metrics["label"] = label
        pb_results.append(metrics)
        print(f"{label:<22}: Trades={metrics['total_trades']:<6} | Win={metrics['win_rate']:4.1f}% | Gross={metrics['gross_bps']:+6.2f} bps | Net={metrics['net_bps']:+6.2f} bps | Exp={metrics['avg_r']:+6.3f} R", flush=True)

    # -------------------------------------------------------------
    # 4. STOP LOSS VARIATIONS
    # -------------------------------------------------------------
    print("\n--- 4. Testing Stop Loss Variations ---", flush=True)
    sl_types = [
        ("Pullback High/Low", StopLossType.PULLBACK_EXTREME, 0.0, 0.0),
        ("Extreme + 0.1% Buffer", StopLossType.EXTREME_BUFFER_PCT, 0.001, 0.0),
        ("Extreme + 0.5 ATR Buffer", StopLossType.EXTREME_BUFFER_ATR, 0.0, 0.5),
        ("Extreme + 1.0 ATR Buffer", StopLossType.EXTREME_BUFFER_ATR, 0.0, 1.0),
        ("Slow EMA Stop", StopLossType.SLOW_EMA, 0.0, 0.0),
    ]
    sl_results = []
    for label, sl_t, buf_p, buf_atr in sl_types:
        cfg = StrategyConfig(
            fast_ema=8,
            slow_ema=13,
            pullback_type=PullbackType.DIRECTIONAL_CLOSE,
            stop_loss_type=sl_t,
            buffer_pct=buf_p,
            buffer_atr_mult=buf_atr,
            fixed_rr=2.0,
            management_mode=TradeManagementMode.A_FULL_1_2,
        )
        df_sl = run_ema_pullback_universe(config=cfg)
        metrics = calculate_metrics(df_sl)
        metrics["label"] = label
        sl_results.append(metrics)
        print(f"{label:<26}: Trades={metrics['total_trades']:<6} | Win={metrics['win_rate']:4.1f}% | Gross={metrics['gross_bps']:+6.2f} bps | Net={metrics['net_bps']:+6.2f} bps | Exp={metrics['avg_r']:+6.3f} R", flush=True)

    # -------------------------------------------------------------
    # 5. EMA PAIRS AND RR GRID (Sensitivity & Optimization)
    # -------------------------------------------------------------
    print("\n--- 5. Parameter Grid: EMA Pairs x Risk-to-Reward Ratios ---", flush=True)
    ema_pairs = [(5, 15), (8, 13), (9, 21), (10, 20), (13, 34)]
    rr_ratios = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
    grid_results = []

    for f_ema, s_ema in ema_pairs:
        for rr in rr_ratios:
            cfg = StrategyConfig(
                fast_ema=f_ema,
                slow_ema=s_ema,
                pullback_type=PullbackType.DIRECTIONAL_CLOSE,
                stop_loss_type=StopLossType.EXTREME_BUFFER_ATR,
                buffer_atr_mult=0.5,
                fixed_rr=rr,
                management_mode=TradeManagementMode.A_FULL_1_2,
            )
            df_g = run_ema_pullback_universe(config=cfg)
            metrics = calculate_metrics(df_g)
            metrics["fast_ema"] = f_ema
            metrics["slow_ema"] = s_ema
            metrics["rr"] = rr
            grid_results.append(metrics)
            print(f"EMA {f_ema:2d}/{s_ema:2d} | RR 1:{rr:<3.1f} -> Trades={metrics['total_trades']:<5} | Win={metrics['win_rate']:4.1f}% | Gross={metrics['gross_bps']:+5.2f} bps | Net={metrics['net_bps']:+5.2f} bps | Exp={metrics['avg_r']:+5.3f} R", flush=True)

    df_grid = pd.DataFrame(grid_results)
    df_grid.to_csv(RESULTS_DIR / "parameter_grid_results.csv", index=False)

    # -------------------------------------------------------------
    # 6. SEGMENTED PERFORMANCE BREAKDOWNS (On Best Candidate)
    # -------------------------------------------------------------
    print("\n--- 6. Segmented Performance Analysis (Long vs Short, Volatility, Time of Day) ---", flush=True)
    best_cfg = StrategyConfig(
        fast_ema=8,
        slow_ema=13,
        pullback_type=PullbackType.DIRECTIONAL_CLOSE,
        stop_loss_type=StopLossType.EXTREME_BUFFER_ATR,
        buffer_atr_mult=0.5,
        fixed_rr=2.0,
        management_mode=TradeManagementMode.A_FULL_1_2,
    )
    df_best = run_ema_pullback_universe(config=best_cfg)
    df_best.to_csv(RESULTS_DIR / "trades_ema_pullback_best.csv", index=False)

    # A. Long vs Short
    long_trades = df_best[df_best["direction"] == "LONG"]
    short_trades = df_best[df_best["direction"] == "SHORT"]
    m_long = calculate_metrics(long_trades)
    m_short = calculate_metrics(short_trades)
    print(f"LONG  Setups: {m_long['total_trades']:,} trades | Win: {m_long['win_rate']:.1f}% | Gross: {m_long['gross_bps']:+.2f} bps | Net: {m_long['net_bps']:+.2f} bps | Exp: {m_long['avg_r']:+.3f} R", flush=True)
    print(f"SHORT Setups: {m_short['total_trades']:,} trades | Win: {m_short['win_rate']:.1f}% | Gross: {m_short['gross_bps']:+.2f} bps | Net: {m_short['net_bps']:+.2f} bps | Exp: {m_short['avg_r']:+.3f} R", flush=True)

    # B. Volatility Regimes (ATR > Median vs <= Median)
    med_atr = df_best["atr_at_entry"].median()
    high_vol = df_best[df_best["atr_at_entry"] > med_atr]
    low_vol = df_best[df_best["atr_at_entry"] <= med_atr]
    m_high_vol = calculate_metrics(high_vol)
    m_low_vol = calculate_metrics(low_vol)
    print(f"High Volatility Regime: {m_high_vol['total_trades']:,} trades | Win: {m_high_vol['win_rate']:.1f}% | Gross: {m_high_vol['gross_bps']:+.2f} bps | Net: {m_high_vol['net_bps']:+.2f} bps | Exp: {m_high_vol['avg_r']:+.3f} R", flush=True)
    print(f"Low Volatility Regime : {m_low_vol['total_trades']:,} trades | Win: {m_low_vol['win_rate']:.1f}% | Gross: {m_low_vol['gross_bps']:+.2f} bps | Net: {m_low_vol['net_bps']:+.2f} bps | Exp: {m_low_vol['avg_r']:+.3f} R", flush=True)

    # C. Time of Day Breakdown
    df_best["entry_tod"] = pd.to_datetime(df_best["entry_time"]).dt.hour * 60 + pd.to_datetime(df_best["entry_time"]).dt.minute
    morning = df_best[(df_best["entry_tod"] >= 570) & (df_best["entry_tod"] < 690)]  # 09:30 - 11:30
    midday = df_best[(df_best["entry_tod"] >= 690) & (df_best["entry_tod"] < 780)]   # 11:30 - 13:00
    afternoon = df_best[(df_best["entry_tod"] >= 780)]                              # 13:00 - 14:30
    m_morning = calculate_metrics(morning)
    m_midday = calculate_metrics(midday)
    m_afternoon = calculate_metrics(afternoon)
    print(f"Morning (09:30-11:30): {m_morning['total_trades']:,} trades | Win: {m_morning['win_rate']:.1f}% | Gross: {m_morning['gross_bps']:+.2f} bps | Net: {m_morning['net_bps']:+.2f} bps | Exp: {m_morning['avg_r']:+.3f} R", flush=True)
    print(f"Midday  (11:30-13:00): {m_midday['total_trades']:,} trades | Win: {m_midday['win_rate']:.1f}% | Gross: {m_midday['gross_bps']:+.2f} bps | Net: {m_midday['net_bps']:+.2f} bps | Exp: {m_midday['avg_r']:+.3f} R", flush=True)
    print(f"Afternoon(13:00-14:30): {m_afternoon['total_trades']:,} trades | Win: {m_afternoon['win_rate']:.1f}% | Gross: {m_afternoon['gross_bps']:+.2f} bps | Net: {m_afternoon['net_bps']:+.2f} bps | Exp: {m_afternoon['avg_r']:+.3f} R", flush=True)

    # D. Day of Week Breakdown
    df_best["dayofweek"] = pd.to_datetime(df_best["entry_time"]).dt.day_name()
    dow_results = {}
    for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        sub_d = df_best[df_best["dayofweek"] == d]
        m_d = calculate_metrics(sub_d)
        dow_results[d] = m_d
        print(f"{d:<10}: {m_d['total_trades']:,} trades | Win: {m_d['win_rate']:.1f}% | Gross: {m_d['gross_bps']:+.2f} bps | Net: {m_d['net_bps']:+.2f} bps | Exp: {m_d['avg_r']:+.3f} R", flush=True)

    # -------------------------------------------------------------
    # 7. ROBUSTNESS TESTING: In-Sample vs Out-of-Sample & Walk-Forward
    # -------------------------------------------------------------
    print("\n--- 7. Robustness: In-Sample vs Out-of-Sample & Walk-Forward ---", flush=True)
    df_best["entry_date"] = pd.to_datetime(df_best["entry_time"]).dt.date
    unique_dates = np.sort(df_best["entry_date"].unique())
    midpoint_date = unique_dates[len(unique_dates) // 2]

    in_sample = df_best[df_best["entry_date"] < midpoint_date]
    out_sample = df_best[df_best["entry_date"] >= midpoint_date]
    m_is = calculate_metrics(in_sample)
    m_oos = calculate_metrics(out_sample)
    print(f"In-Sample  (Year 1, < {midpoint_date}): {m_is['total_trades']:,} trades | Win: {m_is['win_rate']:.1f}% | Gross: {m_is['gross_bps']:+.2f} bps | Net: {m_is['net_bps']:+.2f} bps | Exp: {m_is['avg_r']:+.3f} R", flush=True)
    print(f"Out-Sample (Year 2, >= {midpoint_date}): {m_oos['total_trades']:,} trades | Win: {m_oos['win_rate']:.1f}% | Gross: {m_oos['gross_bps']:+.2f} bps | Net: {m_oos['net_bps']:+.2f} bps | Exp: {m_oos['avg_r']:+.3f} R", flush=True)

    # 4-Slice Walk Forward
    n_slices = 4
    slice_size = len(unique_dates) // n_slices
    wf_results = []
    for k in range(n_slices):
        start_d = unique_dates[k * slice_size]
        end_d = unique_dates[min((k + 1) * slice_size - 1, len(unique_dates) - 1)]
        sub_wf = df_best[(df_best["entry_date"] >= start_d) & (df_best["entry_date"] <= end_d)]
        m_wf = calculate_metrics(sub_wf)
        m_wf["slice"] = k + 1
        m_wf["start_date"] = str(start_d)
        m_wf["end_date"] = str(end_d)
        wf_results.append(m_wf)
        print(f"WF Window {k+1} ({start_d} to {end_d}): {m_wf['total_trades']:,} trades | Win: {m_wf['win_rate']:.1f}% | Gross: {m_wf['gross_bps']:+.2f} bps | Net: {m_wf['net_bps']:+.2f} bps | Exp: {m_wf['avg_r']:+.3f} R", flush=True)

    # -------------------------------------------------------------
    # 8. RANDOMIZED DIRECTION CONTROL TEST
    # -------------------------------------------------------------
    print("\n--- 8. Randomized Direction Control Test (Signal vs Volatility Artifact) ---", flush=True)
    np.random.seed(42)
    inv_gross_bps = -df_best["gross_bps"].to_numpy()
    inv_cost_bps = df_best["cost_bps"].to_numpy()
    inv_net_bps = inv_gross_bps - inv_cost_bps
    m_inverted_gross = float(np.mean(inv_gross_bps))
    m_inverted_net = float(np.mean(inv_net_bps))
    print(f"Real Direction    : Gross = {m_is['gross_bps']:+.2f} bps | Net = {m_is['net_bps']:+.2f} bps", flush=True)
    print(f"Inverted Direction: Gross = {m_inverted_gross:+.2f} bps | Net = {m_inverted_net:+.2f} bps", flush=True)

    # -------------------------------------------------------------
    # 9. MONTE CARLO SIMULATION (1,000 Iterations)
    # -------------------------------------------------------------
    print("\n--- 9. Monte Carlo Simulation (1,000 Resamples) ---", flush=True)
    n_sims = 1000
    n_sample_trades = len(df_best)
    pnl_series = df_best["net_pnl"].to_numpy()

    mc_max_dds = []
    mc_final_equities = []
    mc_max_loss_streaks = []
    initial_cap = 100_000.0

    for sim in range(n_sims):
        sampled_pnl = np.random.choice(pnl_series, size=n_sample_trades, replace=True)
        eq = initial_cap + np.cumsum(sampled_pnl)
        pk = np.maximum.accumulate(eq)
        dd = (eq - pk) / pk * 100.0
        mc_max_dds.append(abs(np.min(dd)))
        mc_final_equities.append(eq[-1])

        is_l = (sampled_pnl <= 0).astype(int)
        c_l = 0
        m_l = 0
        for val in is_l:
            if val == 1:
                c_l += 1
                if c_l > m_l:
                    m_l = c_l
            else:
                c_l = 0
        mc_max_loss_streaks.append(m_l)

    mc_dd_p50 = np.percentile(mc_max_dds, 50)
    mc_dd_p95 = np.percentile(mc_max_dds, 95)
    mc_dd_p99 = np.percentile(mc_max_dds, 99)
    mc_dd_max = np.max(mc_max_dds)
    mc_loss_streak_p95 = np.percentile(mc_max_loss_streaks, 95)
    prob_ruin_50pct = np.mean(np.array(mc_max_dds) >= 50.0) * 100.0

    print(f"Monte Carlo 50th Percentile Max Drawdown: {mc_dd_p50:.1f}%", flush=True)
    print(f"Monte Carlo 95th Percentile Max Drawdown: {mc_dd_p95:.1f}%", flush=True)
    print(f"Monte Carlo 99th Percentile Max Drawdown: {mc_dd_p99:.1f}%", flush=True)
    print(f"Monte Carlo Worst-Case Max Drawdown     : {mc_dd_max:.1f}%", flush=True)
    print(f"Monte Carlo 95th Percentile Losing Streak: {mc_loss_streak_p95:.0f} trades", flush=True)
    print(f"Probability of >=50% Account Drawdown    : {prob_ruin_50pct:.1f}%", flush=True)

    # -------------------------------------------------------------
    # 10. GENERATE HIGH-RESOLUTION CHARTS & FIGURES
    # -------------------------------------------------------------
    print("\n--- 10. Generating Visual Charts ---", flush=True)
    _plot_equity_and_drawdown(df_best, RESULTS_DIR / "equity_and_drawdown.png")
    _plot_trade_management_comparison(mgmt_results, RESULTS_DIR / "trade_management_comparison.png")
    _plot_pullback_comparison(pb_results, RESULTS_DIR / "pullback_definitions_comparison.png")
    _plot_parameter_sensitivity(df_grid, RESULTS_DIR / "parameter_sensitivity.png")
    _plot_monte_carlo_distribution(mc_max_dds, mc_final_equities, RESULTS_DIR / "monte_carlo_distribution.png")

    # Save summary report JSON
    summary_report = {
        "baseline_1_2": m_base_1_2,
        "baseline_1_3": m_base_1_3,
        "trade_management": mgmt_results,
        "pullback_definitions": pb_results,
        "stop_loss_variations": sl_results,
        "segmented_long": m_long,
        "segmented_short": m_short,
        "segmented_high_vol": m_high_vol,
        "segmented_low_vol": m_low_vol,
        "time_of_day": {
            "morning": m_morning,
            "midday": m_midday,
            "afternoon": m_afternoon,
        },
        "day_of_week": dow_results,
        "in_sample": m_is,
        "out_of_sample": m_oos,
        "walk_forward": wf_results,
        "monte_carlo": {
            "p50_max_dd": mc_dd_p50,
            "p95_max_dd": mc_dd_p95,
            "p99_max_dd": mc_dd_p99,
            "max_dd": mc_dd_max,
            "p95_loss_streak": mc_loss_streak_p95,
            "prob_ruin_50pct": prob_ruin_50pct,
        },
    }
    with open(RESULTS_DIR / "comprehensive_summary.json", "w") as f:
        json.dump(summary_report, f, indent=2)

    print(f"\nAll analysis complete! Results and charts saved to {RESULTS_DIR}", flush=True)
    return summary_report


def _plot_equity_and_drawdown(df: pd.DataFrame, output_path: Path):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=False, gridspec_kw={'height_ratios': [2.5, 1]})
    
    initial_cap = 100_000.0
    cum_gross = initial_cap + np.cumsum(df["gross_pnl"])
    cum_net = initial_cap + np.cumsum(df["net_pnl"])
    peak_net = np.maximum.accumulate(cum_net)
    dd_pct = (cum_net - peak_net) / peak_net * 100.0

    trade_idx = np.arange(len(df))
    ax1.plot(trade_idx, cum_gross, label="Gross Equity (Zero Cost)", color="#2563eb", linewidth=1.5)
    ax1.plot(trade_idx, cum_net, label="Net Equity (After Statutory Costs & Slippage)", color="#dc2626", linewidth=1.5)
    ax1.axhline(initial_cap, color="#6b7280", linestyle="--", alpha=0.7, label="Initial Capital (Rs 1,00,000)")
    ax1.set_title("8/13 EMA Pullback Strategy — Cumulative Equity Curve", fontsize=13, fontweight="bold", pad=10)
    ax1.set_ylabel("Account Equity (Rs)", fontsize=11)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left")

    ax2.fill_between(trade_idx, dd_pct, 0, color="#dc2626", alpha=0.3)
    ax2.plot(trade_idx, dd_pct, color="#dc2626", linewidth=1)
    ax2.set_title("Underwater Drawdown (%)", fontsize=11, fontweight="bold", pad=5)
    ax2.set_xlabel("Trade Sequence Number", fontsize=11)
    ax2.set_ylabel("Drawdown %", fontsize=11)
    ax2.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_trade_management_comparison(mgmt_results: List[Dict[str, Any]], output_path: Path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    labels = [m["label"].replace("Strategy ", "") for m in mgmt_results]
    gross_bps = [m["gross_bps"] for m in mgmt_results]
    net_bps = [m["net_bps"] for m in mgmt_results]
    win_rates = [m["win_rate"] for m in mgmt_results]

    x = np.arange(len(labels))
    width = 0.35

    ax1.bar(x - width/2, gross_bps, width, label="Gross bps/trade", color="#3b82f6")
    ax1.bar(x + width/2, net_bps, width, label="Net bps/trade", color="#ef4444")
    ax1.axhline(0, color="black", linestyle="--", linewidth=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=20, ha="right")
    ax1.set_title("Trade Management: Gross vs Net Edge (bps)", fontweight="bold")
    ax1.set_ylabel("Basis Points per Trade")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend()

    ax2.bar(labels, win_rates, color="#10b981", width=0.5)
    ax2.set_title("Trade Management: Realized Win Rate (%)", fontweight="bold")
    ax2.set_ylabel("Win Rate (%)")
    ax2.set_xticklabels(labels, rotation=20, ha="right")
    ax2.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_pullback_comparison(pb_results: List[Dict[str, Any]], output_path: Path):
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [p["label"] for p in pb_results]
    gross_bps = [p["gross_bps"] for p in pb_results]
    net_bps = [p["net_bps"] for p in pb_results]

    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width/2, gross_bps, width, label="Gross bps", color="#3b82f6")
    ax.bar(x + width/2, net_bps, width, label="Net bps", color="#ef4444")
    ax.axhline(0, color="black", linestyle="--", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_title("Comparison of 5 Pullback Definitions (Gross vs Net bps)", fontweight="bold")
    ax.set_ylabel("Basis Points per Trade")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_parameter_sensitivity(df_grid: pd.DataFrame, output_path: Path):
    pivot = df_grid.pivot(index="fast_ema", columns="rr", values="net_bps")
    
    fig, ax = plt.subplots(figsize=(9, 6))
    cax = ax.matshow(pivot.values, cmap="RdYlGn", interpolation="nearest")
    fig.colorbar(cax)

    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_xticklabels([f"1:{col}" for col in pivot.columns])
    ax.set_yticklabels([f"Fast {idx}" for idx in pivot.index])
    ax.set_title("Parameter Sensitivity: Net Edge (bps) across EMA & RR", fontweight="bold", pad=20)
    ax.set_xlabel("Risk-to-Reward Ratio")
    ax.set_ylabel("Fast EMA Length")

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            ax.text(j, i, f"{val:+.1f}", ha="center", va="center", color="black" if -15 < val < 5 else "white", fontweight="bold")

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_monte_carlo_distribution(max_dds: List[float], final_equities: List[float], output_path: Path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    ax1.hist(max_dds, bins=30, color="#ef4444", edgecolor="black", alpha=0.7)
    ax1.axvline(np.percentile(max_dds, 50), color="blue", linestyle="--", label=f"Median: {np.percentile(max_dds, 50):.1f}%")
    ax1.axvline(np.percentile(max_dds, 95), color="black", linestyle="--", label=f"95th %ile: {np.percentile(max_dds, 95):.1f}%")
    ax1.set_title("Monte Carlo: Maximum Drawdown Distribution (%)", fontweight="bold")
    ax1.set_xlabel("Max Drawdown (%)")
    ax1.set_ylabel("Simulation Frequency")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend()

    ax2.hist(final_equities, bins=30, color="#3b82f6", edgecolor="black", alpha=0.7)
    ax2.axvline(100_000.0, color="red", linestyle="--", label="Initial Capital (Rs 100k)")
    ax2.axvline(np.median(final_equities), color="green", linestyle="--", label=f"Median Final Eq: Rs {np.median(final_equities):,.0f}")
    ax2.set_title("Monte Carlo: Final Equity Distribution", fontweight="bold")
    ax2.set_xlabel("Final Equity (Rs)")
    ax2.set_ylabel("Simulation Frequency")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


if __name__ == "__main__":
    run_all_investigations()
