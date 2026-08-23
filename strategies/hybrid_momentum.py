"""
Hybrid intraday-to-delivery momentum — signal generation and level calculation.

*** REJECTED. Do not trade this. ***

The screener below was tested by backtest/hybrid_momentum/test_screener_gate.py
and failed all three of its pre-registered criteria on the development window:
the next-day open-to-close edge over the equal-weight universe is -6.2 bps
(t = -2.55), the rank ordering is not monotone — the BOTTOM-ranked three names
beat the top three — and it beat only 8 of 20 random-selection seeds.

The design exactly as originally proposed does worse still: -11.1 bps vs the
universe on open-to-close (t = -4.18) and -6.2 bps on close-to-close
(t = -2.23), and it underperforms equal-weighting the universe at every
holding period from 1 to 20 days.

No execution engine was built, because there is no point executing a selection
that loses to picking at random. The module is kept because the corrected
factor construction and the level maths below are the record of WHY it fails,
and because the gate script imports them. compute_levels() and gap_check() are
consequently unused by anything that trades — they are here so the corrected
reward:risk arithmetic is written down rather than remembered.

One result survived the gate and is NOT this strategy: at a 40-day hold the
corrected screener beats the universe by +117 bps (t = 2.55). That is a
multi-week position with no intraday leg and no conversion, and it is close to
what backtest/momentum_delivery/ already trades and has already validated.

Everything below this line describes the design as built and tested.

Broker-agnostic and consistent with the rest of strategies/: this module decides
WHAT to buy and AT WHAT LEVELS. It never charges costs and never simulates a
fill — backtest/hybrid_momentum/ does both.

The product
-----------
Screen daily after the close, buy 1-3 names MIS at the next open with
pre-computed SL/TP, and convert whatever is in profit at 15:00 into CNC to be
managed over the following days. Capital is Rs.5,000, which is small enough
that the cost model drives the design rather than decorating it.

Why the factor set is not the one originally proposed
-----------------------------------------------------
The proposal scored six factors at 25/20/20/15/10/10. Measured against
data/daily/ (205 symbols, 15 years) before any of this was written, two of the
six carry no information at all and one is pointed the wrong way:

1. "Relative strength vs Nifty" = roc20(stock) - roc20(index). The index term
   is a single number per date, identical for every symbol, and subtracting a
   per-date constant cannot reorder a cross-sectional ranking. It was
   rank-identical to plain roc20 on 500 of 500 dates tested. As a *score* it is
   dead weight; it survives here only as a market-regime filter, where
   comparing the index to its own history does do something.

2. "Above the 50-DMA" was listed as both a hard filter and a 15% weight. Once
   it is a filter every survivor scores the same, so the weight is 15% of
   nothing. It is a filter here, and only a filter.

3. The momentum leg was a 20-day ROC with no skip. That window is dominated by
   short-term reversal — the same effect strategies/momentum_xs.py skips a
   month to avoid. Ranked on it, the top names went on to UNDERPERFORM the
   equal-weight universe at every horizon out to 20 days, and the bottom-ranked
   control beat the top-ranked one. Moving to a 60-day lookback with a 5-day
   skip improves matters but does not rescue them: on the development window
   the corrected composite still only beats the universe at a 40-day hold
   (+117 bps, t = 2.55). At 10 days it is +84 against the universe's +85.

What is left is four factors, weighted 45/25/15/15, scored as cross-sectional
percentile ranks rather than raw values so no factor's units dominate. The
20-day momentum leg was 0.77 rank-correlated with near-20d-high — close to one
factor wearing two hats — and the corrected 60/skip-5 leg decorrelates from it
to -0.05, so the four inputs as built are genuinely independent. That did not
make the composite work: it scores WORSE than its own best single factor
(momentum alone is +5.7 bps vs the universe at t = 2.03; the blend is +0.8 at
t = 0.31), which is what adding uninformative factors to a ranking does.

Level calculation
-----------------
The proposal derived a 1:5 intraday reward:risk from "risk 0.3x ATR, reward
1.5x ATR". That understates risk by the distance from the entry to yesterday's
low. The stop sits BELOW yesterday's low by 0.3 ATR, so the real risk per share
is (entry - prev_low) + 0.3 ATR, which for a name opening near its highs is
routinely 1-1.5 ATR. The realised ratio is nearer 1:1.

Two changes make the ratio a controlled parameter instead of an emergent one:
  - the stop is capped at max_risk_atr x ATR below entry, so risk is bounded;
  - the target is a multiple of ACTUAL risk, not of ATR.

Everything downstream reports reward:risk net of costs, via
backtest.costs.net_levels. A "+5% target" on Rs.5,000 is +4.04% after the round
trip, and on Rs.1,667 it is +2.67% - the flat Rs.20 DP charge does not care how
small the position is.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.corporate_actions import detect_price_steps

# Dates where the cross-sectional panel collapses to a handful of symbols:
# Muhurat sessions, exchange incidents and truncated feeds. A cross-sectional
# ranking computed on 13 of 205 names is not a ranking, and a trailing-return
# window that spans one is contaminated. Dropped by coverage rather than by a
# hardcoded list so the rule keeps working when the data is refreshed.
MIN_CROSS_SECTION = 100


@dataclass
class HybridConfig:
    """
    Parameters for the hybrid screener.

    Defaults are the pre-registered baseline. Anything changed from these
    counts against the multiple-testing budget - keep a running count, and see
    the walk-forward result in the README for why chasing the best in-sample
    variant is a losing move here.
    """
    # --- momentum leg ---
    lookback_days: int = 60          # ~3 months
    skip_days: int = 5               # avoids the short-term reversal window
    channel_days: int = 20           # window for the near-high factor
    trend_ma: int = 50               # hard filter; 0 disables
    atr_period: int = 14

    # --- factor weights (must sum to 1.0) ---
    w_momentum: float = 0.45
    w_near_high: float = 0.25
    w_volume: float = 0.15
    w_volatility: float = 0.15

    # --- hard filters ---
    min_price: float = 50.0
    max_price: float = 5_000.0
    min_adv: float = 5e7             # Rs.5 Cr median daily traded value
    min_history_days: int = 90
    regime_filter: bool = True       # only trade when the index is above its own trend_ma

    # --- selection ---
    n_positions: int = 1             # 1 by default: see the DP-charge note above

    # --- intraday levels ---
    sl_atr_buffer: float = 0.3       # stop sits this far below yesterday's low
    max_risk_atr: float = 1.0        # ...but never further than this below entry
    r_mult: float = 1.5              # target = entry + r_mult x actual risk

    # --- delivery leg ---
    delivery_tp: float = 0.05        # arm A: +5%
    delivery_sl: float = 0.03        # arm A: -3% (positive magnitude)
    max_hold_days: int = 10          # arm A
    trail_ma: int = 0                # arm B: trail this MA instead of a fixed TP

    # --- pre-market gap filter ---
    gap_down_limit: float = -0.01    # skip if the open is more than 1% below prev close
    gap_up_confirm: float = 0.005

    def validate(self):
        w = self.w_momentum + self.w_near_high + self.w_volume + self.w_volatility
        if abs(w - 1.0) > 1e-9:
            raise ValueError(f"factor weights must sum to 1.0, got {w}")
        if self.skip_days < 0 or self.lookback_days <= 0:
            raise ValueError("lookback_days must be positive and skip_days non-negative")
        return self


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
#
# portfolio.load_daily() returns closes and volumes only. The screener needs
# High and Low as well - for ATR, for the 20-day channel and for the previous
# day's low that the stop is anchored to - so this loads the full OHLCV panel.
# The corporate-action repair reuses data/corporate_actions.detect_price_steps
# and truncates all five frames at the same cutoff, so a symbol repaired here
# is repaired exactly as it is for the momentum work.

def load_daily_ohlc(data_dir: Path = None, repair_corporate_actions: bool = True,
                    min_cross_section: int = MIN_CROSS_SECTION,
                    report: bool = False):
    """
    Load every daily CSV into aligned open/high/low/close/volume frames.

    Returns a dict of five DataFrames sharing one DatetimeIndex, one column per
    symbol. Gaps inside a symbol's own history are forward-filled (holidays and
    halts, where the symbol simply did not trade); leading NaNs are left alone
    so `eligible` reads them as 'not listed yet'.
    """
    data_dir = data_dir or (PROJECT_ROOT / "data" / "daily")
    files = sorted(Path(data_dir).glob("*_1day.csv"))
    if not files:
        raise FileNotFoundError(
            f"No daily data in {data_dir}. Run:\n"
            f"  python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15"
        )

    cols = {"open": {}, "high": {}, "low": {}, "close": {}, "volume": {}}
    for f in files:
        sym = f.stem.replace("_1day", "")
        df = pd.read_csv(f, parse_dates=["datetime"]).set_index("datetime")
        df.index = df.index.tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        for c in cols:
            cols[c][sym] = df[c]

    panel = {c: pd.DataFrame(v).sort_index() for c, v in cols.items()}

    # Drop dates where the cross-section collapses - see MIN_CROSS_SECTION.
    coverage = panel["close"].notna().sum(axis=1)
    dropped = sorted(coverage[(coverage > 0) & (coverage < min_cross_section)].index)
    keep = coverage >= min_cross_section
    panel = {c: v.loc[keep] for c, v in panel.items()}

    events = {}
    if repair_corporate_actions:
        events = detect_price_steps(panel["close"])
        for sym, hits in events.items():
            if sym not in panel["close"].columns:
                continue
            last = max(ts for ts, _, _ in hits)
            for c in panel:
                panel[c].loc[panel[c].index < last, sym] = np.nan

    # Forward-fill interior gaps only.
    for c in panel:
        seen = panel[c].notna().cumsum() > 0
        panel[c] = panel[c].ffill().where(seen)

    if report:
        return panel, {"dropped_dates": dropped, "corporate_actions": events}
    return panel


def restrict(panel: dict, symbols) -> dict:
    """Narrow a panel to a symbol subset - used to screen inside the intraday 50."""
    keep = [s for s in symbols if s in panel["close"].columns]
    return {c: v[keep] for c, v in panel.items()}


# ---------------------------------------------------------------------------
# Indicators - all vectorised over the whole panel, all point-in-time.
#
# Every frame returned is indexed so that row D is computable from data up to
# and including D's close. Nothing downstream may use row D to trade on D.
# ---------------------------------------------------------------------------

def true_range(panel: dict) -> pd.DataFrame:
    """Daily true range. The overnight gap IS legitimate range on a daily bar."""
    h, l, c = panel["high"], panel["low"], panel["close"]
    pc = c.shift(1)
    return pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()]).groupby(level=0).max()


def indicators(panel: dict, cfg: HybridConfig) -> dict:
    """Every derived series the screener and the level calculator need."""
    h, l, c, v = panel["high"], panel["low"], panel["close"], panel["volume"]

    hi = h.rolling(cfg.channel_days).max()
    lo = l.rolling(cfg.channel_days).min()
    atr = true_range(panel).rolling(cfg.atr_period).mean()

    return {
        # 60-day ROC skipping the last 5 days - the reversal window.
        "momentum": c.shift(cfg.skip_days) / c.shift(cfg.skip_days + cfg.lookback_days) - 1.0,
        # Position inside the 20-day channel: 1.0 = at the high.
        "near_high": ((c - lo) / (hi - lo)).replace([np.inf, -np.inf], np.nan),
        "volume_exp": v.rolling(5).mean() / v.rolling(20).mean(),
        # <1 means the recent range is contracting. Negated at scoring time so
        # that, like every other factor, higher is better.
        "atr_ratio": atr.rolling(5).mean() / atr.rolling(20).mean(),
        "atr": atr,
        "ma_trend": c.rolling(cfg.trend_ma).mean() if cfg.trend_ma else None,
        "adv": (c * v).rolling(20).median(),
        "prev_low": l.shift(1),
        "prev_close": c.shift(1),
    }


def equal_weight_index(panel: dict) -> pd.Series:
    """
    The index, built as the equal-weight mean of the universe.

    data/ carries no NIFTY price series - only nifty50.json, which is a list of
    symbol names. This is also the benchmark the rest of the repo already uses
    (momentum_xs.make_buyhold_signal_fn), so the regime filter and the
    performance benchmark are the same object.
    """
    rets = panel["close"].pct_change()
    return (1.0 + rets.mean(axis=1).fillna(0.0)).cumprod()


# ---------------------------------------------------------------------------
# Filters and scoring
# ---------------------------------------------------------------------------

def eligible(panel: dict, ind: dict, cfg: HybridConfig) -> pd.DataFrame:
    """
    Point-in-time tradability mask, one boolean per symbol per date.

    Computed only from trailing data, never from a statistic over the whole
    sample - that would leak future knowledge of which names turned out liquid.
    """
    c = panel["close"]
    ok = c.notna()
    ok &= c >= cfg.min_price
    ok &= c <= cfg.max_price
    ok &= ind["adv"] >= cfg.min_adv
    ok &= c.notna().cumsum() >= cfg.min_history_days
    if cfg.trend_ma and ind["ma_trend"] is not None:
        ok &= c > ind["ma_trend"]                      # hard filter, not a score
    for k in ("momentum", "near_high", "volume_exp", "atr_ratio", "atr"):
        ok &= ind[k].notna()
    return ok.fillna(False)


def market_regime_ok(panel: dict, cfg: HybridConfig) -> pd.Series:
    """
    Is the market itself in an uptrend?

    This is where 'relative strength vs the index' earns its place. Comparing
    each stock to the index is rank-preserving and therefore useless, but
    comparing the INDEX to its own moving average gates the whole book - in a
    downtrend, no position is taken at all.
    """
    if not cfg.regime_filter:
        return pd.Series(True, index=panel["close"].index)
    idx = equal_weight_index(panel)
    return (idx > idx.rolling(cfg.trend_ma or 50).mean()).fillna(False)


def factor_ranks(ind: dict, mask: pd.DataFrame) -> dict:
    """
    Each factor as a cross-sectional percentile rank within the eligible set.

    Ranking rather than z-scoring keeps a single outlier from dominating the
    composite, and puts every factor on the same 0-1 scale so the weights mean
    what they say.
    """
    def pr(df, ascending=True):
        return df.where(mask).rank(axis=1, pct=True, ascending=ascending)

    return {
        "momentum": pr(ind["momentum"]),
        "near_high": pr(ind["near_high"]),
        "volume_exp": pr(ind["volume_exp"]),
        # Lower atr_ratio = tighter consolidation = better, hence ascending=False.
        "volatility": pr(ind["atr_ratio"], ascending=False),
    }


def composite_score(ind: dict, mask: pd.DataFrame, cfg: HybridConfig) -> pd.DataFrame:
    """Weighted blend of the four percentile-ranked factors. Higher is better."""
    f = factor_ranks(ind, mask)
    return (cfg.w_momentum * f["momentum"]
            + cfg.w_near_high * f["near_high"]
            + cfg.w_volume * f["volume_exp"]
            + cfg.w_volatility * f["volatility"])


def rank_picks(score: pd.DataFrame, mask: pd.DataFrame, n: int,
               ascending: bool = False) -> pd.DataFrame:
    """Boolean frame marking the top (or bottom) n names per date."""
    ranked = score.where(mask).rank(axis=1, ascending=ascending, method="first")
    return (ranked <= n).fillna(False)


def select(score: pd.DataFrame, mask: pd.DataFrame, regime: pd.Series,
           asof, cfg: HybridConfig) -> list:
    """
    The names to buy at the next open, ranked best first.

    Returns [] when the regime filter is off-side or nothing qualifies. Filling
    the book with names that failed the filters would defeat having them.
    """
    if asof not in score.index or not bool(regime.get(asof, False)):
        return []
    row = score.loc[asof].where(mask.loc[asof]).dropna()
    if row.empty:
        return []
    return list(row.sort_values(ascending=False).index[:cfg.n_positions])


# ---------------------------------------------------------------------------
# Level calculation
# ---------------------------------------------------------------------------

def compute_levels(ind: dict, symbol: str, asof, entry_price: float,
                   cfg: HybridConfig) -> dict:
    """
    SL/TP for one position, from the signal date's indicators and the fill price.

    `asof` is the SIGNAL date (the prior close). `entry_price` is the next
    session's fill. Levels are therefore known before the market opens, which
    is the whole point - they can be placed as resting orders.

    The stop is the tighter of two ideas that disagree on purpose:
      - structure: yesterday's low, less a 0.3 ATR buffer so ordinary noise
        under support does not trigger it;
      - risk control: never more than max_risk_atr x ATR below the fill.
    Taking the higher of the two prices bounds risk. Without the cap, a name
    that opens well above yesterday's low carries a stop 1.5 ATR away and the
    advertised reward:risk quietly inverts.
    """
    atr = float(ind["atr"].at[asof, symbol])
    prev_low = float(ind["prev_low"].at[asof, symbol])

    if not np.isfinite(atr) or atr <= 0 or not np.isfinite(prev_low):
        return {}

    structural = prev_low - cfg.sl_atr_buffer * atr
    capped = entry_price - cfg.max_risk_atr * atr
    intra_sl = max(structural, capped)

    risk = entry_price - intra_sl
    if risk <= 0:
        return {}                       # opened at or below its own stop

    return {
        "symbol": symbol,
        "signal_date": asof,
        "entry_price": entry_price,
        "atr": atr,
        "prev_low": prev_low,
        "intra_sl": intra_sl,
        "intra_tp": entry_price + cfg.r_mult * risk,
        "sl_source": "structural" if structural >= capped else "atr_cap",
        "risk_per_share": risk,
        "rr_ratio": cfg.r_mult,
        "risk_pct_of_entry": risk / entry_price,
        "delivery_sl": entry_price * (1.0 - cfg.delivery_sl),
        "delivery_tp": entry_price * (1.0 + cfg.delivery_tp),
    }


def gap_check(open_price: float, prev_close: float, cfg: HybridConfig) -> tuple:
    """
    The pre-market validation step, as (proceed: bool, label: str).

    In live trading this reads Angel One's pre-open auction price at ~09:08. In
    backtest it reads the 09:15 open, which is the SAME NUMBER - the auction's
    equilibrium price is what opens the continuous session - so this filter
    carries no look-ahead.
    """
    if not np.isfinite(open_price) or not np.isfinite(prev_close) or prev_close <= 0:
        return False, "no_price"
    gap = open_price / prev_close - 1.0
    if gap < cfg.gap_down_limit:
        return False, "gap_down"
    if gap > cfg.gap_up_confirm:
        return True, "gap_up_confirmed"
    return True, "flat_open"


# ---------------------------------------------------------------------------
# Controls
#
# Built in from the start rather than bolted on, for the same reason
# momentum_xs.py does it: "does the ranking add anything over picking at
# random" is the question that decides whether any of this is real. The
# intraday phase was killed by exactly this test.
# ---------------------------------------------------------------------------

def make_random_picks(mask: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Pick n eligible names at random per date."""
    rng = np.random.default_rng(seed)
    noise = pd.DataFrame(rng.random(mask.shape), index=mask.index, columns=mask.columns)
    return rank_picks(noise, mask, n)


def make_bottom_picks(score: pd.DataFrame, mask: pd.DataFrame, n: int) -> pd.DataFrame:
    """The WORST-ranked names - should be symmetrically bad if the score is real."""
    return rank_picks(score, mask, n, ascending=True)


def universe_picks(mask: pd.DataFrame) -> pd.DataFrame:
    """
    Every eligible name, equal-weighted - the benchmark.

    This is the bar. A long-only equity strategy making money proves nothing;
    the market rises. Beating this, after costs, is the only result that counts.
    """
    return mask
