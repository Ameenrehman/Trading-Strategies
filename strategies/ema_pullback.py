"""
8/13 EMA Pullback Strategy for Intraday Cash Equity.

Core Architecture:
1. Directional Bias: Fast EMA (default 8) vs Slow EMA (default 13).
   - Positive crossover (Fast > Slow) establishes Bullish bias.
   - Negative crossover (Fast < Slow) establishes Bearish bias.
2. Pullback Detection:
   - Evaluates pullback candles relative to the EMAs without look-ahead.
   - Tested definitions:
     * 'touch_fast': Price dips to/touches Fast EMA.
     * 'touch_slow': Price dips to/touches Slow EMA.
     * 'zone': Candle penetrates the zone between Fast and Slow EMAs.
     * 'directional_close': Candle touches EMA zone and closes in trend direction.
     * 'wick_rejection': Candle tests EMA zone and leaves a rejection wick.
3. Breakout Entry:
   - On close of valid pullback candle, mark High (Long) / Low (Short).
   - Next bar(s) if price breaches mark, enter on breakout at mark price.
   - Expiry: Setup expires if not triggered within max_bars_wait.
4. Stop Loss & Take Profit:
   - Initial Stop Loss at Pullback candle Low (Long) / High (Short) [or buffer/ATR/EMA].
   - Target based on Risk-to-Reward (1:1, 1:1.5, 1:2, 1:2.5, 1:3, 1:4).
5. Trade Management Modes (Strategies A to E):
   - 'A_full_1_2': Full position closed at 1:2 RR.
   - 'B_full_1_3': Full position closed at 1:3 RR.
   - 'C_partial_1_2': 50% closed at 1R -> Move SL to Breakeven -> Remaining 50% at 2R.
   - 'D_partial_1_3': 50% closed at 1R -> Move SL to Breakeven -> Remaining 50% at 3R.
   - 'E_partial_trail': 50% closed at 1R -> Move SL to Breakeven -> Remaining 50% trailed.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
import numpy as np
import pandas as pd


class PullbackType(str, Enum):
    TOUCH_FAST = "touch_fast"
    TOUCH_SLOW = "touch_slow"
    ZONE = "zone"
    DIRECTIONAL_CLOSE = "directional_close"
    WICK_REJECTION = "wick_rejection"


class StopLossType(str, Enum):
    PULLBACK_EXTREME = "pullback_extreme"
    EXTREME_BUFFER_PCT = "extreme_buffer_pct"  # e.g. 0.1% buffer
    EXTREME_BUFFER_ATR = "extreme_buffer_atr"  # e.g. 0.5 ATR buffer
    SLOW_EMA = "slow_ema"
    ATR_FIXED = "atr_fixed"


class TradeManagementMode(str, Enum):
    A_FULL_1_2 = "A_full_1_2"
    B_FULL_1_3 = "B_full_1_3"
    C_PARTIAL_1_2 = "C_partial_1_2"
    D_PARTIAL_1_3 = "D_partial_1_3"
    E_PARTIAL_TRAIL = "E_partial_trail"


@dataclass
class StrategyConfig:
    fast_ema: int = 8
    slow_ema: int = 13
    pullback_type: PullbackType = PullbackType.ZONE
    stop_loss_type: StopLossType = StopLossType.PULLBACK_EXTREME
    buffer_pct: float = 0.001  # 0.1%
    buffer_atr_mult: float = 0.5
    atr_period: int = 14
    fixed_rr: float = 2.0
    management_mode: TradeManagementMode = TradeManagementMode.A_FULL_1_2
    max_setup_bars: int = 3  # Maximum bars to wait for breakout of pullback candle
    min_entry_time: int = 570  # 09:30 IST (minutes from midnight)
    max_entry_time: int = 870  # 14:30 IST
    square_off_time: int = 915  # 15:15 IST
    risk_pct: float = 0.01  # 1% equity risk
    max_leverage: float = 5.0  # MIS leverage cap
    slippage_bps: float = 5.0  # 5 bps per leg slippage
    allow_long: bool = True
    allow_short: bool = True


def compute_ema(values: np.ndarray, period: int) -> np.ndarray:
    """Compute Exponential Moving Average using pandas ewm."""
    return pd.Series(values).ewm(span=period, adjust=False).mean().to_numpy()


def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                is_first_bar: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute day-aware ATR (ignores overnight gap on first bar)."""
    prev_close = np.empty_like(close)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )
    tr[is_first_bar] = (high - low)[is_first_bar]
    return pd.Series(tr).rolling(period, min_periods=1).mean().to_numpy()


def is_valid_pullback(
    direction: int,  # +1 for Long, -1 for Short
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    fast_ema: float,
    slow_ema: float,
    pullback_type: PullbackType,
) -> bool:
    """
    Check if the current closed candle qualifies as a valid pullback.
    direction == +1 (Bullish bias): price is pulling back down toward EMAs.
    direction == -1 (Bearish bias): price is pulling back up toward EMAs.
    """
    if direction == 1:
        # Bullish bias (Fast EMA > Slow EMA)
        upper_ema = max(fast_ema, slow_ema)
        lower_ema = min(fast_ema, slow_ema)

        if pullback_type == PullbackType.TOUCH_FAST:
            # Low reaches or dips below Fast EMA
            return low_p <= fast_ema and high_p >= fast_ema

        elif pullback_type == PullbackType.TOUCH_SLOW:
            # Low reaches or dips below Slow EMA
            return low_p <= slow_ema and high_p >= slow_ema

        elif pullback_type == PullbackType.ZONE:
            # Candle enters the zone between Fast and Slow EMAs
            return low_p <= upper_ema and high_p >= lower_ema

        elif pullback_type == PullbackType.DIRECTIONAL_CLOSE:
            # Touches EMA zone AND closes bullish (green candle)
            in_zone = low_p <= upper_ema and high_p >= lower_ema
            return in_zone and (close_p > open_p)

        elif pullback_type == PullbackType.WICK_REJECTION:
            # Rejection wick: lower shadow is at least 30% of total candle range and touches zone
            candle_range = high_p - low_p
            if candle_range <= 0:
                return False
            lower_wick = min(open_p, close_p) - low_p
            in_zone = low_p <= upper_ema
            return in_zone and (lower_wick / candle_range >= 0.3)

    elif direction == -1:
        # Bearish bias (Fast EMA < Slow EMA)
        upper_ema = max(fast_ema, slow_ema)
        lower_ema = min(fast_ema, slow_ema)

        if pullback_type == PullbackType.TOUCH_FAST:
            # High reaches or rises above Fast EMA
            return high_p >= fast_ema and low_p <= fast_ema

        elif pullback_type == PullbackType.TOUCH_SLOW:
            # High reaches or rises above Slow EMA
            return high_p >= slow_ema and low_p <= slow_ema

        elif pullback_type == PullbackType.ZONE:
            # Candle enters the zone between Slow and Fast EMAs
            return high_p >= lower_ema and low_p <= upper_ema

        elif pullback_type == PullbackType.DIRECTIONAL_CLOSE:
            # Touches EMA zone AND closes bearish (red candle)
            in_zone = high_p >= lower_ema and low_p <= upper_ema
            return in_zone and (close_p < open_p)

        elif pullback_type == PullbackType.WICK_REJECTION:
            # Rejection wick: upper shadow is at least 30% of total candle range and touches zone
            candle_range = high_p - low_p
            if candle_range <= 0:
                return False
            upper_wick = high_p - max(open_p, close_p)
            in_zone = high_p >= lower_ema
            return in_zone and (upper_wick / candle_range >= 0.3)

    return False
