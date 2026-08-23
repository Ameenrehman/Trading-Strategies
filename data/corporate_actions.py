"""
Detect and neutralise unadjusted corporate actions in daily price series.

Why this exists
---------------
Angel One serves *unadjusted* daily closes. A demerger, a bonus issue or a
post-insolvency relisting therefore appears as a clean single-day step in an
otherwise continuous series — a step that no shareholder actually experienced.

For most strategies that is a nuisance. For cross-sectional momentum it is
fatal, because the ranking is computed from a trailing 12-month return. One
unadjusted action parks a phantom stock at the very top or the very bottom of
the ranking **every rebalance for a full year**.

Measured on the Nifty 200 daily set (205 symbols, 2011-2026), exactly three
symbols carry such a step:

    ADANIENT    2015-06-03    -80.9%   demerger (Ports/Transmission/Power spun out)
    PATANJALI   2020-01-27   +406.2%   Ruchi Soya relisting after 75-day suspension
    YESBANK     2020-03-06    -56.1%   RBI moratorium and reconstruction

The first two are pure artifacts — an ADANIENT holder received shares in the
demerged entities and did not lose 80%, and a Ruchi Soya holder did not make
406% overnight. The third is a genuine loss to shareholders.

The detector cannot tell those apart, and it should not try: distinguishing
them requires knowing the corporate event, which is exactly the information
free price data lacks. So the rule is applied uniformly and the affected
symbols are reported, rather than hand-picking which ones to "fix" — that
choice is where bias creeps in unnoticed.

Treatment
---------
History is truncated to begin *after* the last detected step, so the symbol
behaves exactly like one that listed on that date. Truncation is preferred to
dropping the symbol entirely: dropping ADANIENT would remove a genuine Nifty
constituent from 15 years of the universe, which is its own selection bias.

Cost of a false positive (YESBANK loses its pre-2020 history) is one symbol's
early data. Cost of a false negative is a fabricated top-ranked stock held for
twelve consecutive rebalances. The thresholds are deliberately set to err
toward removing data rather than inventing signal.
"""

import pandas as pd

# A split, bonus, demerger or relisting produces a step far outside anything a
# liquid large-cap does in one session. Genuine single-day moves in the Nifty
# 200 top out near -30% (COVID, PSU-bank news); these thresholds sit well clear
# of that so ordinary crashes are NOT treated as data errors.
DROP_THRESHOLD = -0.50      # -50% in one day
JUMP_THRESHOLD = 1.00       # +100% in one day


def detect_price_steps(closes: pd.DataFrame,
                       drop_threshold: float = DROP_THRESHOLD,
                       jump_threshold: float = JUMP_THRESHOLD) -> dict:
    """
    Find single-day steps consistent with an unadjusted corporate action.

    Returns {symbol: [(timestamp, pct_move, calendar_gap_days), ...]}. The gap
    is reported because a step preceded by a long trading halt is almost
    certainly a restructuring rather than a market move.
    """
    found = {}
    for sym in closes.columns:
        s = closes[sym].dropna()
        if len(s) < 2:
            continue
        r = s.pct_change()
        gaps = s.index.to_series().diff().dt.days
        hits = r[(r <= drop_threshold) | (r >= jump_threshold)]
        if len(hits):
            found[sym] = [(dt, float(v), int(gaps.loc[dt]) if pd.notna(gaps.loc[dt]) else 0)
                          for dt, v in hits.items()]
    return found


def truncate_before_steps(closes: pd.DataFrame, volumes: pd.DataFrame = None,
                          drop_threshold: float = DROP_THRESHOLD,
                          jump_threshold: float = JUMP_THRESHOLD):
    """
    Blank each affected symbol's history up to and including its last step.

    Returns (closes, volumes, events). Frames are copies; the originals are
    left untouched. `events` is the detect_price_steps mapping, so callers can
    report exactly what was removed instead of silently altering the data.
    """
    events = detect_price_steps(closes, drop_threshold, jump_threshold)
    if not events:
        return closes, volumes, events

    closes = closes.copy()
    volumes = volumes.copy() if volumes is not None else None
    for sym, hits in events.items():
        last_step = max(dt for dt, _, _ in hits)
        # NaN, not zero: momentum_xs treats NaN as "not tradable yet", which is
        # precisely the semantics we want for a pre-restructuring price series.
        closes.loc[closes.index <= last_step, sym] = float("nan")
        if volumes is not None:
            volumes.loc[volumes.index <= last_step, sym] = 0.0
    return closes, volumes, events


def format_events(events: dict) -> str:
    """One-line-per-event summary for printing in a backtest report."""
    if not events:
        return "  No unadjusted corporate actions detected."
    lines = []
    for sym in sorted(events):
        for dt, v, gap in events[sym]:
            g = f", after a {gap}-day trading halt" if gap > 10 else ""
            lines.append(f"  {sym:<12} {dt.date()}  {v*100:+7.1f}%{g}"
                         f"  -> history truncated to start after this date")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    # backtest/portfolio.py's load_daily() lives on the main branch with the
    # delivery-momentum work. This branch carries only the hybrid strategy, so
    # the scan uses its OHLCV loader instead — same CSVs, same repair, and it
    # additionally drops the handful of dates whose cross-section collapses.
    from strategies.hybrid_momentum import load_daily_ohlc

    panel = load_daily_ohlc(repair_corporate_actions=False)
    closes = panel["close"]
    events = detect_price_steps(closes)
    print("=" * 78)
    print("  UNADJUSTED CORPORATE ACTION SCAN")
    print("=" * 78)
    print(f"  Universe: {closes.shape[1]} symbols, "
          f"{closes.index[0].date()} -> {closes.index[-1].date()}")
    print(f"  Thresholds: <= {DROP_THRESHOLD*100:.0f}% or >= +{JUMP_THRESHOLD*100:.0f}% in one day")
    print()
    print(format_events(events))
    print()
    print(f"  {sum(len(v) for v in events.values())} event(s) across "
          f"{len(events)} symbol(s).")
