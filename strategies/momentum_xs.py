"""
Cross-sectional momentum with a trend filter — signal generation.

Broker-agnostic, consistent with the rest of strategies/: this module only
decides WHAT to hold on a given date. The portfolio backtester in
backtest/portfolio.py decides how to trade it and charges the costs.

How positions are exited — no stop-loss, no take-profit
-------------------------------------------------------
This is the biggest conceptual difference from the intraday work, so it is
worth stating plainly: there is no per-trade SL or TP. **The rebalance IS the
exit.** On each rebalance date the whole universe is re-ranked and:

  hold  - still inside the top N by momentum AND still above its 200-DMA
  sell  - dropped out of the top N, OR fell below its 200-DMA
  buy   - newly qualified on both counts

So the holding period is variable and endogenous. A stock that keeps trending
is held indefinitely (winners are allowed to run, which is where momentum's
return actually comes from); a stock that rolls over is gone at the next
rebalance, so the worst case is roughly one month of decay.

The 200-DMA filter is the systematic stop. It is a portfolio-level, scheduled
rule rather than an intraday trigger.

Why not add a hard stop-loss:
  1. Momentum is a cross-sectional, statistical edge. Per-trade stops convert a
     diversified edge into a set of path-dependent bets and historically reduce
     momentum returns — the fat right tail is the whole point, and stops
     truncate the distribution on the side you cannot afford to lose.
  2. Turnover is the dominant cost lever here (30% vs 50% monthly turnover is
     1.67% vs 2.78% a year in drag). Stops raise turnover.
  3. A stop that fires between rebalances re-introduces exactly the
     path-dependence and timing sensitivity the intraday work failed on.

The genuine risk this creates is gap risk between rebalances: a name can fall
sharply on news and be held until month-end. Rather than assume that away,
three optional exit modifiers below let it be TESTED. All default to off, so
the baseline is the classic construction:

  disaster_stop_pct  - hard stop checked daily, e.g. 0.25 for -25% from entry
  trend_exit_daily   - check the 200-DMA daily instead of only at rebalance
  exit_rank_buffer   - hold until a name drops out of the top (n + buffer),
                       which REDUCES turnover rather than increasing it

Ranking construction
--------------------
12-1 momentum: trailing 12-month return skipping the most recent month. The
skip is standard and not cosmetic — the most recent month carries short-term
reversal, which contaminates the momentum signal if included.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MomentumConfig:
    """
    Parameters for the cross-sectional momentum strategy.

    Defaults are the classic construction. Anything switched on beyond these
    counts against the multiple-testing budget — keep a running count.
    """
    lookback_days: int = 252        # ~12 months
    skip_days: int = 21             # ~1 month, avoids short-term reversal
    n_positions: int = 20
    trend_ma: int = 200             # 200-DMA filter; 0 disables it
    min_history_days: int = 273     # lookback + skip; no ranking without it
    min_adv: float = 5_000_000.0    # min median daily traded value, trailing 3m

    # Optional exit modifiers — all off by default (see module docstring)
    disaster_stop_pct: float = 0.0
    trend_exit_daily: bool = False
    exit_rank_buffer: int = 0


def momentum_scores(closes: pd.DataFrame, asof, cfg: MomentumConfig) -> pd.Series:
    """
    12-1 momentum for every symbol, as of `asof`.

    Point-in-time by construction: only rows up to and including `asof` are
    used, so nothing downstream can see the future.
    """
    hist = closes.loc[:asof]
    # Needs lookback + skip + 1 rows: iloc[-1 - skip - lookback] is the oldest
    # row touched. Guarding on lookback + skip is an off-by-one that only bites
    # when a rebalance lands on the exact boundary — daily rebalancing does,
    # monthly never did.
    if len(hist) < cfg.lookback_days + cfg.skip_days + 1:
        return pd.Series(dtype=float)

    end = hist.iloc[-1 - cfg.skip_days]                       # skip recent month
    start = hist.iloc[-1 - cfg.skip_days - cfg.lookback_days]
    with np.errstate(divide="ignore", invalid="ignore"):
        score = (end / start) - 1.0
    return score.replace([np.inf, -np.inf], np.nan).dropna()


def above_trend(closes: pd.DataFrame, asof, cfg: MomentumConfig) -> pd.Series:
    """Boolean per symbol: is the last close above its `trend_ma`-day average?"""
    hist = closes.loc[:asof]
    if cfg.trend_ma <= 0:
        return pd.Series(True, index=closes.columns)
    if len(hist) < cfg.trend_ma:
        return pd.Series(False, index=closes.columns)
    ma = hist.iloc[-cfg.trend_ma:].mean()
    return (hist.iloc[-1] > ma).fillna(False)


def eligible(closes: pd.DataFrame, volumes: pd.DataFrame, asof,
             cfg: MomentumConfig) -> pd.Series:
    """
    Point-in-time tradability filter.

    Computed only from data available at `asof` — never from a statistic over
    the whole sample, which would leak future information about which names
    turned out to be liquid.
    """
    hist_c = closes.loc[:asof]
    ok = hist_c.notna().sum() >= cfg.min_history_days

    if volumes is not None and cfg.min_adv > 0:
        hist_v = volumes.loc[:asof].iloc[-63:]               # ~3 months
        hist_p = hist_c.iloc[-63:]
        adv = (hist_v * hist_p).median()
        ok = ok & (adv >= cfg.min_adv)

    # A price must exist right now to trade it.
    ok = ok & hist_c.iloc[-1].notna()
    return ok.fillna(False)


def select(closes: pd.DataFrame, volumes: pd.DataFrame, asof,
           cfg: MomentumConfig, currently_held=None) -> list:
    """
    The names to hold from `asof` until the next rebalance.

    `currently_held` enables `exit_rank_buffer`: an existing holding is kept
    while it stays inside the top (n_positions + exit_rank_buffer), so a name
    hovering around the cutoff isn't churned in and out every month. New
    positions must still make the strict top n_positions.

    Returns fewer than n_positions when not enough names qualify — the balance
    stays in cash. Backfilling with names that fail the trend filter would
    defeat the point of having one.
    """
    scores = momentum_scores(closes, asof, cfg)
    if scores.empty:
        return []

    ok = eligible(closes, volumes, asof, cfg)
    trend = above_trend(closes, asof, cfg)

    qualified = scores[ok.reindex(scores.index, fill_value=False)
                       & trend.reindex(scores.index, fill_value=False)]
    if qualified.empty:
        return []

    ranked = qualified.sort_values(ascending=False)
    selected = list(ranked.index[:cfg.n_positions])

    if cfg.exit_rank_buffer and currently_held:
        keep_zone = set(ranked.index[:cfg.n_positions + cfg.exit_rank_buffer])
        retained = [s for s in currently_held if s in keep_zone]
        # Retained names first, then top-ranked newcomers to fill the book.
        out = list(dict.fromkeys(retained))
        for s in selected:
            if len(out) >= cfg.n_positions:
                break
            if s not in out:
                out.append(s)
        selected = out[:cfg.n_positions]

    return selected


def make_signal_fn(cfg: MomentumConfig, volumes: pd.DataFrame = None):
    """Adapt `select` to the (closes, asof, held) signature portfolio.py expects."""
    def signal_fn(closes, asof, held=None):
        return select(closes, volumes, asof, cfg, currently_held=held)
    return signal_fn


# ---------------------------------------------------------------------------
# Controls — the analog of the randomized-direction test that decided the
# intraday work. Built here rather than bolted on later, because "does the
# ranking add anything over picking at random" is the question that matters.
# ---------------------------------------------------------------------------

def make_random_signal_fn(cfg: MomentumConfig, volumes: pd.DataFrame, seed: int):
    """Pick n_positions at random from the eligible, in-trend universe."""
    rng = np.random.default_rng(seed)

    def signal_fn(closes, asof, held=None):
        scores = momentum_scores(closes, asof, cfg)
        if scores.empty:
            return []
        ok = eligible(closes, volumes, asof, cfg)
        trend = above_trend(closes, asof, cfg)
        pool = list(scores[ok.reindex(scores.index, fill_value=False)
                           & trend.reindex(scores.index, fill_value=False)].index)
        if not pool:
            return []
        k = min(cfg.n_positions, len(pool))
        return list(rng.choice(pool, size=k, replace=False))
    return signal_fn


def make_bottom_signal_fn(cfg: MomentumConfig, volumes: pd.DataFrame):
    """Hold the WORST names by momentum rank — should be symmetrically bad."""
    def signal_fn(closes, asof, held=None):
        scores = momentum_scores(closes, asof, cfg)
        if scores.empty:
            return []
        ok = eligible(closes, volumes, asof, cfg)
        trend = above_trend(closes, asof, cfg)
        qualified = scores[ok.reindex(scores.index, fill_value=False)
                           & trend.reindex(scores.index, fill_value=False)]
        if qualified.empty:
            return []
        return list(qualified.sort_values(ascending=True).index[:cfg.n_positions])
    return signal_fn


def make_buyhold_signal_fn(cfg: MomentumConfig, volumes: pd.DataFrame):
    """
    Equal-weight the whole eligible universe — the benchmark.

    This is the bar the strategy has to clear. A long-only equity strategy
    making money proves nothing; the market rises. Beating this, after costs,
    is the only result that counts.
    """
    def signal_fn(closes, asof, held=None):
        ok = eligible(closes, volumes, asof, cfg)
        return list(ok[ok].index)
    return signal_fn
