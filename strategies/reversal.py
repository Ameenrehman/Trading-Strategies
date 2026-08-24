"""
Short-horizon reversal screener - long only, NSE cash, delivery (CNC).

*** STATUS: REJECTED AT THE HOLDOUT. Do not fund this. ***

    Development window (2011-2024): all six pre-registered criteria cleared.
    Edge +27.3 bps per 10-day window (t = 2.29); the book returned 33.96% CAGR
    against 22.91% for the equal-weight universe, at a smaller drawdown.

    Sealed holdout (2024-2026): +8.7 bps (t = 0.94), 1 of 5 evaluable criteria.
    That window's standard error was 9.2 bps, so a +27.3 bps edge would have
    printed t = 2.97 - it had the power to confirm the development result and
    did not. The sign survived (still beat 20 of 20 random seeds, bottom of the
    ranking still worst); the magnitude did not.

    The likeliest reading: a weak real effect whose in-sample size was inflated
    because the design - horizon, components, pick count - was chosen on the
    same window it was measured on. Kept in the tree because it is the honest
    record of that, and because it is the natural candidate for a forward paper
    test, which is now the only clean measurement left.

What this trades, and why it looks backwards
--------------------------------------------
The feasibility study (backtest/nextday/feasibility.py) found that every
informative daily-bar feature in this universe has a NEGATIVE information
coefficient. Distance above the 20-DMA, RSI, consecutive up days, closing near
the 20-day high - all of them predict WEAKNESS over the following days.

So this screener buys what just fell. Its components are the same six features
the study measured, sign-flipped: a high score means a liquid name that has
recently sold off, closed near the bottom of its range, and sits well below its
own 20-day high. That is the opposite of a breakout screener, and it is the
direction the data actually supports.

Every component is individually weak - the strongest managed t = 1.74 at a
5-day hold, and two of the six are worthless alone. The composite is the signal
(+24.3 bps, t = 2.72). That is worth stating plainly rather than burying: this
strategy has no single factor to fall back on if the blend stops working.

The size problem, and what is done about it
-------------------------------------------
The strongest factor at a 10-20 day horizon is not reversal at all - it is
turnover, with a negative sign, i.e. "buy the smaller names". It is also the
factor most contaminated by survivorship: this universe is today's index
membership applied to history, so a name that was small ten years ago and is
still in the index necessarily grew into it. Splitting the universe by cohort,
the effect is roughly 50% stronger among symbols that entered the panel late -
exactly the names where the bias is worst.

It cannot be cleaned without a point-in-time constituent list, which the free
data does not provide. So it is excluded from the score AND actively controlled
for: with `size_neutral`, names are ranked against peers in the same turnover
band, so a pick can never be a disguised bet on smallness. That costs real
measured edge (+32.9 -> +27.3 bps at a 10-day hold) and is worth it, because
the edge it costs is the part most likely to be an artifact.

Holding period
--------------
Reversal decays. Size-neutral edge by hold: 3d +19.2 (t 2.77), 5d +21.5
(t 3.06), 10d +27.3 (t 2.29), 20d +34.7 (t 1.37). Per-trade edge keeps rising
while significance falls, because a longer hold means fewer independent windows.
10 days is the default: it carries the most edge per round trip of any horizon
that still clears t > 2.

This module decides WHAT to buy and AT WHAT LEVELS. It never charges costs and
never simulates a fill; that belongs to the backtest.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.features import build_features, eligibility, ATR_PERIOD  # noqa: E402
from strategies.panel import load_daily_ohlc  # noqa: E402

# The six components, all sign-flipped when scored. Named here rather than
# inline so the gate can score each one separately against the blend.
COMPONENTS = ("ret1", "ret5", "dist_ma20", "clv", "updays5", "high_prox")


@dataclass
class ReversalConfig:
    """Every knob, with the value the study supports and why."""

    # --- signal ---
    components: tuple = COMPONENTS
    size_neutral: bool = True      # rank within turnover bands; see module docstring
    turnover_bands: int = 5

    # --- selection ---
    n_positions: int = 5           # top-1 has more edge/name but t 2.38 vs 2.72
    hold_days: int = 10            # most edge per round trip that still clears t > 2

    # --- levels (ATR-derived: ATR predicts tomorrow's range at r = 0.49,
    #     while direction is a coin flip, so size the barriers, not the call) ---
    atr_period: int = ATR_PERIOD
    sl_atr: float = 2.0
    tp_atr: float = 3.0

    # Enforcing those barriers is MEASURED TO LOSE MONEY here, so it is off by
    # default. On a mean-reverting signal a stop sells precisely the thing the
    # signal bought - more weakness - and realises a loss the trade existed to
    # recover. In the book test every stop setting was worse than no stop on
    # return, and a 3-ATR stop made the drawdown worse too (34.0% -> 23.6% CAGR,
    # max DD -35.5% -> -41.8%). The levels are still computed and reported: they
    # are useful as position-sizing and risk context. They are not an exit rule.
    use_barriers: bool = False

    # "close": score into the close and fill at the closing price. "open": buy at
    # the next open. Same picks, same days - but the open entry forfeits the
    # overnight move, worth ~3 points of CAGR in the book test, because the
    # benchmark is close-to-close and keeps it.
    entry_timing: str = "close"

    def validate(self) -> None:
        if not self.components:
            raise ValueError("components must be non-empty")
        for c in self.components:
            if c not in COMPONENTS:
                raise ValueError(f"unknown component {c!r}; expected one of {COMPONENTS}")
        if self.n_positions < 1:
            raise ValueError("n_positions must be >= 1")
        if self.hold_days < 1:
            raise ValueError("hold_days must be >= 1")
        if self.sl_atr <= 0 or self.tp_atr <= 0:
            raise ValueError("sl_atr and tp_atr must be positive")
        if self.turnover_bands < 1:
            raise ValueError("turnover_bands must be >= 1")
        if self.entry_timing not in ("close", "open"):
            raise ValueError("entry_timing must be 'close' or 'open'")


# ---------------------------------------------------------------------------
# Scoring - all vectorised over the panel, all point-in-time.
# ---------------------------------------------------------------------------

def xs_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional percentile rank, centred on zero."""
    return df.rank(axis=1, pct=True) - 0.5


def indicators(panel: dict) -> tuple[dict, pd.DataFrame]:
    return build_features(panel)


def eligible(panel: dict) -> pd.DataFrame:
    return eligibility(panel)


def composite_score(feats: dict, mask: pd.DataFrame, cfg: ReversalConfig) -> pd.DataFrame:
    """
    Higher score = more oversold = better candidate.

    The negation is the whole point: each component's raw value predicts the
    next few days NEGATIVELY, so the blend is minus the mean of their
    cross-sectional ranks. Ranks rather than raw values, so no component's scale
    dominates the blend.
    """
    ranks = [xs_rank(feats[c].where(mask)) for c in cfg.components]
    return -sum(ranks) / len(ranks)


def size_neutralise(score: pd.DataFrame, turnover: pd.DataFrame,
                    mask: pd.DataFrame, bands: int = 5) -> pd.DataFrame:
    """
    Re-rank the score inside turnover bands.

    After this, a name scores well only by being oversold RELATIVE TO PEERS OF
    ITS OWN SIZE. It removes the strongest raw factor in the data on purpose -
    see the module docstring on survivorship.
    """
    tq = turnover.where(mask).rank(axis=1, pct=True)
    out = score.copy()
    for b in range(bands):
        lo, hi = b / bands, (b + 1) / bands
        band = (tq > lo) & (tq <= hi) if b else (tq >= 0) & (tq <= hi)
        out = out.where(~band, score.where(band).rank(axis=1, pct=True) - 0.5)
    return out.where(mask)


def score_panel(panel: dict, cfg: ReversalConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Convenience: (score, mask, atr) for a loaded panel."""
    cfg.validate()
    feats, atr = indicators(panel)
    mask = eligible(panel)
    score = composite_score(feats, mask, cfg)
    if cfg.size_neutral:
        score = size_neutralise(score, feats["turnover"], mask, cfg.turnover_bands)
    return score, mask, atr


# ---------------------------------------------------------------------------
# Selection and controls
# ---------------------------------------------------------------------------

def select(score: pd.DataFrame, mask: pd.DataFrame, n: int) -> pd.DataFrame:
    """Boolean frame: the n best-scoring eligible names on each date."""
    return (score.rank(axis=1, ascending=False) <= n) & mask & score.notna()


def bottom_picks(score: pd.DataFrame, mask: pd.DataFrame, n: int) -> pd.DataFrame:
    """The mirror control. If the ranking carries information, these lose."""
    return (score.rank(axis=1, ascending=True) <= n) & mask & score.notna()


def random_picks(mask: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Randomised control drawn from the same eligible set on the same dates."""
    rng = np.random.default_rng(seed)
    noise = pd.DataFrame(rng.random(mask.shape), index=mask.index, columns=mask.columns)
    return (noise.where(mask).rank(axis=1, ascending=False) <= n) & mask


def universe_picks(mask: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight the eligible universe - the benchmark every edge is paired against."""
    return mask.copy()


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def levels(entry_price: float, atr: float, cfg: ReversalConfig) -> dict:
    """
    ATR-derived stop and target for one position.

    Grounded in the one thing the study found genuinely forecastable: ATR
    predicts tomorrow's high-low range at r = 0.49, while the direction of the
    move is a coin flip (sign agreement 50.6%). So the levels are sized from
    volatility and NOT from a predicted move - there is no honest way to quote
    "this will go up X%".
    """
    if not np.isfinite(entry_price) or not np.isfinite(atr) or entry_price <= 0 or atr <= 0:
        return {}
    sl = entry_price - cfg.sl_atr * atr
    tp = entry_price + cfg.tp_atr * atr
    risk = entry_price - sl
    return {
        "entry": entry_price,
        "stop_loss": sl,
        "take_profit": tp,
        "atr": atr,
        "risk_per_share": risk,
        "sl_pct": (sl / entry_price - 1) * 100,
        "tp_pct": (tp / entry_price - 1) * 100,
        "rr_ratio": (tp - entry_price) / risk if risk > 0 else float("nan"),
    }


def levels_frame(entry: pd.Series, atr: pd.Series, cfg: ReversalConfig) -> pd.DataFrame:
    """Vectorised `levels` for a Series of entries indexed by symbol."""
    sl = entry - cfg.sl_atr * atr
    tp = entry + cfg.tp_atr * atr
    return pd.DataFrame({
        "entry": entry, "stop_loss": sl, "take_profit": tp, "atr": atr,
        "risk_per_share": entry - sl,
        "sl_pct": (sl / entry - 1) * 100,
        "tp_pct": (tp / entry - 1) * 100,
        "rr_ratio": (tp - entry) / (entry - sl),
    })


if __name__ == "__main__":
    cfg = ReversalConfig()
    cfg.validate()
    panel = load_daily_ohlc()
    score, mask, atr = score_panel(panel, cfg)
    asof = score.dropna(how="all").index[-1]

    picks = select(score, mask, cfg.n_positions).loc[asof]
    names = list(picks[picks].index)
    entry = panel["close"].loc[asof, names]
    lv = levels_frame(entry, atr.loc[asof, names], cfg).round(2)

    print("=" * 78)
    print("  REJECTED AT THE HOLDOUT - see the module docstring.")
    print("  A +27.3 bps development edge (t 2.29) did not replicate out of")
    print("  sample: +8.7 bps (t 0.94), on a window with the power to detect it.")
    print("  This list is for a forward PAPER test. Do not fund it.")
    print("=" * 78)
    print(f"\nReversal screener - scored on {asof.date()} close, "
          f"{int(mask.loc[asof].sum())} eligible names")
    print(f"hold {cfg.hold_days} trading days, {cfg.n_positions} positions, "
          f"SL {cfg.sl_atr} ATR / TP {cfg.tp_atr} ATR, "
          f"size-neutral={cfg.size_neutral}\n")
    print(lv.to_string())
    print(f"\nEntry: {cfg.entry_timing} of the scoring day. "
          f"Exit: after {cfg.hold_days} sessions, on time.")
    print("SL/TP are volatility-derived RISK CONTEXT, not an exit rule -")
    print("enforcing them cost 10 points of CAGR in the backtest and made the")
    print("drawdown worse. This screener ranks; it does not forecast how far a")
    print("name will move (signed R-squared was 0.000).")
