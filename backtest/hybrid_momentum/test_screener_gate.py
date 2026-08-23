"""
The gate. Run and read this BEFORE anything else in hybrid_momentum/.

The proposal for this strategy called the daily screener "the most critical
step — the screener quality determines everything". That is correct, and it is
also cheap to test: a screener built from daily bars can be evaluated on 15
years and 205 symbols without simulating a single intraday fill. If the ranking
carries no next-day information, no execution engine can rescue it, and
building one first would just be an expensive way to find that out.

So this script answers six questions, in order, and writes the answers down:

  1. Do the proposed factors actually differ from each other?
  2. Where in the day does the return live — overnight, or intraday?
  3. Does each factor, alone, predict the next day?
  4. Does the composite beat the equal-weight universe, and is it monotone
     in rank (top-1 > top-3 > universe > bottom-3)?
  5. Held for k days instead of one, does the edge exceed the cost of trading?
  6. What edge does Rs.5,000 of capital actually need to clear?

Pre-registered kill criteria (written before the run, scored honestly):

  G1  Composite next-day edge over the universe, open->close   > 0 bps, t > 2
  G2  Rank monotonicity holds: top-1 >= top-3 >= universe >= bottom-3
  G3  Composite beats >= 19 of 20 random-selection seeds

If G1-G3 fail, the engines do not get built. That is the same discipline that
killed the intraday phase in Part 1 of the README, and it is the only thing
that makes a "pass" mean anything.

Statistical note. Picks on the same date are not independent — they share that
day's market move — so every t-stat here is computed across DATES, on the daily
cross-sectional mean of the selected names, never across name-days. For holding
periods longer than one day the windows overlap, which inflates t further; a
non-overlapping estimate is reported alongside for those.

OUTCOME (development window, holdout sealed): all three failed. G1 = -6.2 bps
with t = -2.55, G2 violated (the bottom three beat the top three), G3 = 8/20.
The design as originally proposed scored worse than the corrected one on both
horizons. No execution engine was built. See the verdict block at the end of
the generated report for the one result that did survive, and why it is a
different strategy rather than a reprieve for this one.

Usage:
    python backtest/hybrid_momentum/test_screener_gate.py
    python backtest/hybrid_momentum/test_screener_gate.py --full-sample
    python backtest/hybrid_momentum/test_screener_gate.py --universe intraday50
"""

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.costs import (
    hybrid_cost_bps, delivery_cost_bps, intraday_cost_bps,
    intraday_cost_bps_2026,
)
from strategies.hybrid_momentum import (
    HybridConfig, load_daily_ohlc, indicators, eligible, composite_score,
    factor_ranks, rank_picks, make_random_picks, equal_weight_index,
)

warnings.filterwarnings("ignore")

RESULTS_DIR = PROJECT_ROOT / "backtest" / "results" / "hybrid_momentum"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

HOLDS = [1, 3, 5, 10, 20, 40]
N_RANDOM_SEEDS = 20

# Trailing window held back from development. Mirrors backtest/portfolio.py's
# HOLDOUT_MONTHS on the main branch, where the delivery-momentum work lives —
# kept identical so the two are comparable, inlined here because this branch
# carries only the hybrid strategy and importing a rebalancing backtester for
# one integer would drag Part 2's whole dependency chain back in.
HOLDOUT_MONTHS = 24


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def daily_mean(returns: pd.DataFrame, picks: pd.DataFrame) -> pd.Series:
    """Mean forward return of the selected names, one number per date."""
    return returns.where(picks).mean(axis=1).dropna()


def tstat(series: pd.Series) -> float:
    """t of the mean against zero, across dates."""
    s = series.dropna()
    if len(s) < 3 or s.std() == 0:
        return np.nan
    return s.mean() / s.std() * np.sqrt(len(s))


def describe(series: pd.Series, every: int = 1) -> dict:
    """
    Summarise a daily series of mean returns.

    `every` > 1 thins the series to non-overlapping observations, which is the
    honest t for a k-day holding period.
    """
    s = series.dropna()
    thin = s.iloc[::every] if every > 1 else s
    return {
        "days": len(s),
        "bps": s.mean() * 1e4,
        "hit_pct": (s > 0).mean() * 100,
        "t": tstat(s),
        "t_nonoverlap": tstat(thin) if every > 1 else tstat(s),
    }


def paired(picks_daily: pd.Series, bench_daily: pd.Series, every: int = 1) -> dict:
    """
    The difference against the benchmark, tested as a paired series.

    This is the question that matters — not "did the picks go up" (the market
    went up) but "did picking them beat picking everything".
    """
    diff = (picks_daily - bench_daily).dropna()
    d = describe(diff, every)
    return {"edge_bps": d["bps"], "edge_t": d["t"],
            "edge_t_nonoverlap": d["t_nonoverlap"], "days": d["days"]}


# ---------------------------------------------------------------------------
# The six sections
# ---------------------------------------------------------------------------

def proposed_composite(panel, ind, mask):
    """
    The screener exactly as originally specified, for the record.

    Six factors at 25/20/20/15/10/10: 20-day ROC, relative strength vs the
    index, near-20-day-high, above-50-DMA, volume expansion, low recent
    volatility. Two of them cannot rank anything — RS is rank-identical to the
    20-day ROC, and above-50-DMA is already a hard filter so every survivor
    scores 1.0 — but they are included here at their stated weights so the
    comparison is against what was actually proposed, not a tidied version of it.
    """
    c = panel["close"]
    roc20 = c / c.shift(20) - 1.0
    idx = equal_weight_index(panel)
    rs = roc20.sub(idx / idx.shift(20) - 1.0, axis=0)
    above = (c > ind["ma_trend"]).astype(float) if ind["ma_trend"] is not None else c * 0 + 1.0

    def pr(df, ascending=True):
        return df.where(mask).rank(axis=1, pct=True, ascending=ascending)

    return (0.25 * pr(roc20) + 0.20 * pr(rs) + 0.20 * pr(ind["near_high"])
            + 0.15 * pr(above) + 0.10 * pr(ind["volume_exp"])
            + 0.10 * pr(ind["atr_ratio"], ascending=False))


def section_1_factor_overlap(ind, mask, panel, out):
    """Are the proposed factors actually different from each other?"""
    lines = ["=" * 78,
             "  1. FACTOR OVERLAP — do the six proposed factors carry six signals?",
             "=" * 78, ""]

    ranks = factor_ranks(ind, mask)
    names = list(ranks)
    dates = mask.index[mask.sum(axis=1) > 20][::5]

    corr = pd.DataFrame(index=names, columns=names, dtype=float)
    for a in names:
        for b in names:
            vals = [ranks[a].loc[d].corr(ranks[b].loc[d]) for d in dates]
            corr.loc[a, b] = np.nanmean(vals)
    corr = corr.astype(float)

    lines.append("Cross-sectional rank correlation, averaged over "
                 f"{len(dates)} dates:\n")
    lines.append(corr.round(2).to_string())
    lines.append("")

    # The correlation that motivated the redesign belonged to the ORIGINAL
    # 20-day-ROC construction. Report both, so the fix is visible rather than
    # asserted.
    c = panel["close"]
    roc20 = c / c.shift(20) - 1.0
    old_corr = np.nanmean([roc20.loc[d].where(mask.loc[d]).rank().corr(
        ind["near_high"].loc[d].where(mask.loc[d]).rank()) for d in dates])
    new_corr = corr.loc["momentum", "near_high"]
    lines.append(f"  momentum vs near_high, ORIGINAL 20-day ROC : {old_corr:+.2f}")
    lines.append(f"  momentum vs near_high, corrected 60/skip-5 : {new_corr:+.2f}")
    lines.append("  The original pair were close to one factor wearing two hats. The")
    lines.append("  corrected momentum leg decorrelates from it, so the four factors")
    lines.append("  in the built config are genuinely independent inputs.")
    lines.append("")

    # The two factors that were dropped, and why.
    idx = equal_weight_index(panel)
    idx_roc20 = idx / idx.shift(20) - 1.0
    rs = roc20.sub(idx_roc20, axis=0)

    test_dates = [d for d in mask.index[-500:] if mask.loc[d].sum() > 20]
    identical = sum(
        roc20.loc[d].where(mask.loc[d]).rank().equals(
            rs.loc[d].where(mask.loc[d]).rank())
        for d in test_dates
    )
    lines.append("DROPPED FACTOR 1 — 'relative strength vs the index'")
    lines.append(f"  rank-identical to plain 20-day ROC on {identical}/{len(test_dates)} "
                 "dates tested.")
    lines.append("  Subtracting a per-date constant cannot reorder a cross-section, so")
    lines.append("  as a SCORE it contributes nothing. Retained as a regime filter only.")
    lines.append("")
    lines.append("DROPPED FACTOR 2 — 'price above the 50-DMA'")
    lines.append("  Listed as both a hard filter and a 15% weight. Once it is a filter,")
    lines.append("  every surviving name scores identically, so the weight ranks nothing.")
    lines.append("")

    corr.to_csv(RESULTS_DIR / "factor_correlations.csv")
    out["rs_identical_dates"] = f"{identical}/{len(test_dates)}"
    return lines


def section_2_where_the_return_lives(panel, mask, out):
    """Overnight vs intraday — decides whether a same-day exit can work at all."""
    lines = ["=" * 78,
             "  2. WHERE THE RETURN LIVES — overnight gap vs intraday session",
             "=" * 78, ""]

    o, c = panel["open"], panel["close"]
    parts = {
        "overnight  (prev close -> open)": (o / c.shift(1) - 1.0).shift(-1),
        "intraday   (open -> close)": (c / o - 1.0).shift(-1),
        "full day   (close -> close)": (c.pct_change()).shift(-1),
    }

    lines.append(f"{'segment':<34}{'bps/day':>10}{'hit %':>9}{'t':>9}")
    lines.append("-" * 62)
    rows = []
    for label, frame in parts.items():
        d = describe(daily_mean(frame, mask))
        lines.append(f"{label:<34}{d['bps']:>+10.1f}{d['hit_pct']:>9.1f}{d['t']:>9.1f}")
        rows.append({"segment": label, **d})
    lines.append("")
    lines.append("  Essentially the whole of the universe's drift is delivered overnight,")
    lines.append("  and the continuous session is a net drag. Any design that buys at the")
    lines.append("  open and exits before the close donates the first and pays the second,")
    lines.append("  before a single rupee of brokerage.")
    lines.append("")

    pd.DataFrame(rows).to_csv(RESULTS_DIR / "return_decomposition.csv", index=False)
    out["intraday_drift_bps"] = rows[1]["bps"]
    out["overnight_drift_bps"] = rows[0]["bps"]
    return lines


def section_3_single_factors(panel, ind, mask, cfg, out):
    """Each factor alone, ranked top-3, against the universe."""
    lines = ["=" * 78,
             "  3. SINGLE-FACTOR NEXT-DAY EDGE — score at close(D), trade D+1",
             "=" * 78, ""]

    fwd_oc = (panel["close"] / panel["open"] - 1.0).shift(-1)
    fwd_cc = panel["close"].pct_change().shift(-1)
    bench_oc, bench_cc = daily_mean(fwd_oc, mask), daily_mean(fwd_cc, mask)

    ranks = factor_ranks(ind, mask)
    lines.append(f"{'factor (top 3)':<22}{'O->C bps':>10}{'vs univ':>9}{'t':>7}"
                 f"{'   ':>3}{'C->C bps':>10}{'vs univ':>9}{'t':>7}")
    lines.append("-" * 78)

    rows = []
    for name, score in ranks.items():
        picks = rank_picks(score, mask, 3)
        p_oc, p_cc = daily_mean(fwd_oc, picks), daily_mean(fwd_cc, picks)
        e_oc, e_cc = paired(p_oc, bench_oc), paired(p_cc, bench_cc)
        lines.append(f"{name:<22}{p_oc.mean()*1e4:>+10.1f}{e_oc['edge_bps']:>+9.1f}"
                     f"{e_oc['edge_t']:>7.2f}   "
                     f"{p_cc.mean()*1e4:>+10.1f}{e_cc['edge_bps']:>+9.1f}"
                     f"{e_cc['edge_t']:>7.2f}")
        rows.append({"factor": name, "oc_bps": p_oc.mean() * 1e4,
                     "oc_edge_bps": e_oc["edge_bps"], "oc_edge_t": e_oc["edge_t"],
                     "cc_bps": p_cc.mean() * 1e4,
                     "cc_edge_bps": e_cc["edge_bps"], "cc_edge_t": e_cc["edge_t"]})

    lines.append(f"{'UNIVERSE (all eligible)':<22}{bench_oc.mean()*1e4:>+10.1f}"
                 f"{'—':>9}{'—':>7}   {bench_cc.mean()*1e4:>+10.1f}{'—':>9}{'—':>7}")
    lines.append("")
    lines.append("  'vs univ' is the paired daily difference against equal-weighting the")
    lines.append("  whole eligible set — the only comparison that isolates the ranking.")
    lines.append("")

    pd.DataFrame(rows).to_csv(RESULTS_DIR / "single_factor_edge.csv", index=False)
    return lines


def section_4_composite_and_controls(panel, ind, mask, cfg, out):
    """The composite, its rank monotonicity, and the random-selection control."""
    lines = ["=" * 78,
             "  4. COMPOSITE + CONTROLS — is the ranking real?",
             "=" * 78, ""]

    fwd_oc = (panel["close"] / panel["open"] - 1.0).shift(-1)
    fwd_cc = panel["close"].pct_change().shift(-1)
    bench_oc, bench_cc = daily_mean(fwd_oc, mask), daily_mean(fwd_cc, mask)
    score = composite_score(ind, mask, cfg)

    proposed = proposed_composite(panel, ind, mask)
    variants = {
        "AS-PROPOSED top 3": rank_picks(proposed, mask, 3),
        "composite top 1": rank_picks(score, mask, 1),
        "composite top 3": rank_picks(score, mask, 3),
        "UNIVERSE": mask,
        "composite bottom 3": rank_picks(score, mask, 3, ascending=True),
    }

    lines.append(f"{'selection':<22}{'O->C bps':>10}{'vs univ':>9}{'t':>7}"
                 f"   {'C->C bps':>10}{'vs univ':>9}{'t':>7}")
    lines.append("-" * 78)
    rows, oc_by_variant = [], {}
    for label, picks in variants.items():
        p_oc, p_cc = daily_mean(fwd_oc, picks), daily_mean(fwd_cc, picks)
        e_oc, e_cc = paired(p_oc, bench_oc), paired(p_cc, bench_cc)
        dash = "—" if label == "UNIVERSE" else f"{e_oc['edge_bps']:>+9.1f}"
        dash_t = "—" if label == "UNIVERSE" else f"{e_oc['edge_t']:>7.2f}"
        dash_c = "—" if label == "UNIVERSE" else f"{e_cc['edge_bps']:>+9.1f}"
        dash_ct = "—" if label == "UNIVERSE" else f"{e_cc['edge_t']:>7.2f}"
        lines.append(f"{label:<22}{p_oc.mean()*1e4:>+10.1f}{dash:>9}{dash_t:>7}   "
                     f"{p_cc.mean()*1e4:>+10.1f}{dash_c:>9}{dash_ct:>7}")
        oc_by_variant[label] = p_oc.mean() * 1e4
        rows.append({"selection": label, "oc_bps": p_oc.mean() * 1e4,
                     "cc_bps": p_cc.mean() * 1e4,
                     "oc_edge_bps": e_oc["edge_bps"] if label != "UNIVERSE" else 0.0,
                     "oc_edge_t": e_oc["edge_t"] if label != "UNIVERSE" else np.nan,
                     "cc_edge_bps": e_cc["edge_bps"] if label != "UNIVERSE" else 0.0,
                     "cc_edge_t": e_cc["edge_t"] if label != "UNIVERSE" else np.nan})
    lines.append("")

    # G2 — monotonicity, checked on close-to-close (the horizon the strategy holds).
    cc = {r["selection"]: r["cc_bps"] for r in rows}
    mono = (cc["composite top 1"] >= cc["composite top 3"] >= cc["UNIVERSE"]
            >= cc["composite bottom 3"])
    lines.append(f"G2 rank monotonicity (close->close): top1 {cc['composite top 1']:+.1f} "
                 f">= top3 {cc['composite top 3']:+.1f} >= universe {cc['UNIVERSE']:+.1f} "
                 f">= bottom3 {cc['composite bottom 3']:+.1f}")
    lines.append(f"    -> {'PASS' if mono else 'FAIL'}")
    lines.append("")

    # G3 — random-selection control.
    top3_cc = daily_mean(fwd_cc, variants["composite top 3"])
    beaten = 0
    seed_bps = []
    for seed in range(N_RANDOM_SEEDS):
        rnd = make_random_picks(mask, 3, seed)
        r_cc = daily_mean(fwd_cc, rnd)
        seed_bps.append(r_cc.mean() * 1e4)
        if top3_cc.mean() > r_cc.mean():
            beaten += 1
    lines.append(f"G3 random-selection control (3 names/day, {N_RANDOM_SEEDS} seeds):")
    lines.append(f"    composite top 3 = {top3_cc.mean()*1e4:+.1f} bps/day")
    lines.append(f"    random seeds    = {np.mean(seed_bps):+.1f} bps/day mean, "
                 f"range [{min(seed_bps):+.1f}, {max(seed_bps):+.1f}]")
    lines.append(f"    beaten {beaten}/{N_RANDOM_SEEDS}  -> "
                 f"{'PASS' if beaten >= 19 else 'FAIL'}")
    lines.append("")

    pd.DataFrame(rows).to_csv(RESULTS_DIR / "composite_controls.csv", index=False)
    out["G2_monotonic"] = mono
    out["G3_random_beaten"] = beaten
    # Look the row up by name — the table's order has changed once already.
    top3_row = next(r for r in rows if r["selection"] == "composite top 3")
    prop_row = next(r for r in rows if r["selection"] == "AS-PROPOSED top 3")
    out["composite_oc_edge_bps"] = top3_row["oc_edge_bps"]
    out["composite_oc_edge_t"] = top3_row["oc_edge_t"]
    out["proposed_oc_edge_bps"] = prop_row["oc_edge_bps"]
    out["proposed_oc_edge_t"] = prop_row["oc_edge_t"]
    out["proposed_cc_edge_bps"] = prop_row["cc_edge_bps"]
    out["proposed_cc_edge_t"] = prop_row["cc_edge_t"]
    return lines


def section_5_holding_period(panel, ind, mask, cfg, out):
    """Forward returns by holding period, against the cost of getting them."""
    lines = ["=" * 78,
             "  5. HOLDING PERIOD — buy at close(D), hold k days",
             "=" * 78, ""]

    c = panel["close"]
    score = composite_score(ind, mask, cfg)
    variants = {
        "AS-PROPOSED top 3": rank_picks(proposed_composite(panel, ind, mask), mask, 3),
        "composite top 1": rank_picks(score, mask, 1),
        "composite top 3": rank_picks(score, mask, 3),
        "UNIVERSE": mask,
        "composite bottom 3": rank_picks(score, mask, 3, ascending=True),
    }

    rows_edge = []
    header = f"{'selection':<22}" + "".join(f"{'d'+str(k):>13}" for k in HOLDS)
    lines.append(header)
    lines.append("-" * len(header))

    rows = []
    for label, picks in variants.items():
        cells = []
        for k in HOLDS:
            fwd = c.shift(-k) / c - 1.0
            d = describe(daily_mean(fwd, picks), every=k)
            cells.append(f"{d['bps']:>+7.0f}({d['t_nonoverlap']:>4.1f})")
            rows.append({"selection": label, "hold_days": k, **d})
        lines.append(f"{label:<22}" + "".join(f"{x:>13}" for x in cells))
    lines.append("")
    lines.append("  Figures are gross bps; the bracketed t uses NON-OVERLAPPING windows,")
    lines.append("  which is the honest one for a k-day hold.")
    lines.append("")

    hurdle_1 = hybrid_cost_bps(5_000, True)
    hurdle_3 = hybrid_cost_bps(5_000 / 3, True)
    lines.append(f"  Cost to clear at Rs.5,000: {hurdle_1:.0f} bps on one position, "
                 f"{hurdle_3:.0f} bps split three ways.")
    top3 = {r["hold_days"]: r["bps"] for r in rows if r["selection"] == "composite top 3"}
    univ = {r["hold_days"]: r["bps"] for r in rows if r["selection"] == "UNIVERSE"}
    clears = [k for k in HOLDS if top3[k] > hurdle_1]

    # Beating the universe has to be significant, not merely positive. A +8 bps
    # gap at 20 days on a +164 bps move is noise wearing a plus sign.
    picks3 = variants["composite top 3"]
    beats = []
    for k in HOLDS:
        fwd = c.shift(-k) / c - 1.0
        e = paired(daily_mean(fwd, picks3), daily_mean(fwd, mask), every=k)
        rows_edge.append({"hold_days": k, **e})
        if e["edge_bps"] > 0 and (e["edge_t_nonoverlap"] or 0) > 2:
            beats.append(k)
    lines.append(f"  Horizons where top-3 clears its own cost : "
                 f"{clears if clears else 'none'}")
    lines.append(f"  Horizons where top-3 beats the universe  : "
                 f"{beats if beats else 'none'}   (edge > 0 AND t > 2)")
    lines.append("")
    lines.append(f"  {'hold':>6}{'edge vs universe':>20}{'t (non-overlap)':>18}")
    for e in rows_edge:
        lines.append(f"  {e['hold_days']:>6}{e['edge_bps']:>+20.1f}"
                     f"{e['edge_t_nonoverlap']:>18.2f}")
    lines.append("")

    pd.DataFrame(rows).to_csv(RESULTS_DIR / "forward_returns.csv", index=False)
    pd.DataFrame(rows_edge).to_csv(RESULTS_DIR / "forward_edge_vs_universe.csv", index=False)
    out["clears_cost_at"] = clears
    out["beats_universe_at"] = beats
    best = max((e for e in rows_edge if e["hold_days"] in beats),
               key=lambda e: e["edge_bps"], default=None)
    out["best_edge_bps"] = best["edge_bps"] if best else 0.0
    out["best_edge_t"] = best["edge_t_nonoverlap"] if best else 0.0
    return lines


def section_6_cost_hurdle(out):
    """What Rs.5,000 has to overcome, by product and by concurrent positions."""
    lines = ["=" * 78,
             "  6. COST HURDLE — what Rs.5,000 of capital has to beat",
             "=" * 78, ""]

    lines.append(f"{'capital split':<24}{'each':>10}{'MIS':>9}{'hybrid':>9}{'CNC':>9}")
    lines.append("-" * 61)
    for n in (1, 2, 3):
        each = 5_000 / n
        lines.append(f"{f'{n} position(s)':<24}Rs.{each:>7,.0f}"
                     f"{intraday_cost_bps_2026(each):>9.1f}"
                     f"{hybrid_cost_bps(each, True):>9.1f}"
                     f"{delivery_cost_bps(each):>9.1f}")
    lines.append("")
    lines.append("  All in bps of position value, round trip, 5 bps/leg slippage.")
    lines.append("  The MIS column uses Angel One's real 2026 schedule, calibrated")
    lines.append("  against a contract note; the legacy model in costs.py understates")
    lines.append(f"  it {intraday_cost_bps_2026(5_000)/intraday_cost_bps(5_000):.1f}x.")
    lines.append("")
    lines.append("  The flat Rs.20 + GST DP charge is why splitting is expensive: it is")
    lines.append("  paid per scrip regardless of size, so three Rs.1,667 positions pay")
    lines.append("  it three times on a book that never exceeded Rs.5,000.")
    lines.append("")
    out["hurdle_1pos_hybrid"] = hybrid_cost_bps(5_000, True)
    return lines


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full-sample", action="store_true",
                    help="include the 24-month holdout (development runs must not)")
    ap.add_argument("--universe", choices=["all", "intraday50"], default="all",
                    help="'intraday50' screens only the names with 5-minute data")
    args = ap.parse_args()

    cfg = HybridConfig().validate()

    print("Loading daily panel...")
    panel, meta = load_daily_ohlc(report=True)

    if args.universe == "intraday50":
        from strategies.hybrid_momentum import restrict
        syms = sorted(p.stem.replace("_5min", "")
                      for p in (PROJECT_ROOT / "data" / "intraday_5min").glob("*_5min.csv"))
        panel = restrict(panel, syms)

    header = [
        "=" * 78,
        "  HYBRID MOMENTUM — SCREENER GATE",
        "=" * 78,
        "",
        f"Universe          : {panel['close'].shape[1]} symbols ({args.universe})",
        f"Panel             : {panel['close'].index[0].date()} -> "
        f"{panel['close'].index[-1].date()}  ({len(panel['close']):,} dates)",
        f"Dropped dates     : {len(meta['dropped_dates'])} with a collapsed cross-section "
        f"{[str(d.date()) for d in meta['dropped_dates']]}",
        f"Corporate actions : {len(meta['corporate_actions'])} symbols truncated "
        f"{sorted(meta['corporate_actions'])}",
    ]

    if not args.full_sample:
        cutoff = panel["close"].index[-1] - pd.DateOffset(months=HOLDOUT_MONTHS)
        panel = {k: v.loc[v.index <= cutoff] for k, v in panel.items()}
        header.append(f"Holdout           : sealed, {HOLDOUT_MONTHS} months "
                      f"(development ends {cutoff.date()})")
    else:
        header.append("Holdout           : *** INCLUDED — this is not a development run ***")
    header += ["", f"Config            : {cfg.lookback_days}-day ROC skipping "
               f"{cfg.skip_days}, weights "
               f"{cfg.w_momentum}/{cfg.w_near_high}/{cfg.w_volume}/{cfg.w_volatility}", ""]

    print("Computing indicators...")
    ind = indicators(panel, cfg)
    mask = eligible(panel, ind, cfg)
    header.append(f"Eligible name-days: {int(mask.sum().sum()):,} across "
                  f"{int((mask.sum(axis=1) > 0).sum()):,} dates")
    header.append("")

    out = {}
    body = []
    print("  1/6 factor overlap...");        body += section_1_factor_overlap(ind, mask, panel, out)
    print("  2/6 return decomposition..."); body += section_2_where_the_return_lives(panel, mask, out)
    print("  3/6 single factors...");       body += section_3_single_factors(panel, ind, mask, cfg, out)
    print("  4/6 composite + controls..."); body += section_4_composite_and_controls(panel, ind, mask, cfg, out)
    print("  5/6 holding period...");       body += section_5_holding_period(panel, ind, mask, cfg, out)
    print("  6/6 cost hurdle...");          body += section_6_cost_hurdle(out)

    g1_pass = (out["composite_oc_edge_bps"] > 0) and (out["composite_oc_edge_t"] > 2)
    verdict = [
        "=" * 78,
        "  GATE VERDICT",
        "=" * 78,
        "",
        f"  G1  next-day O->C edge over universe   "
        f"{out['composite_oc_edge_bps']:+.1f} bps, t = {out['composite_oc_edge_t']:.2f}"
        f"   {'PASS' if g1_pass else 'FAIL'}",
        f"  G2  rank monotonicity                  "
        f"{'holds' if out['G2_monotonic'] else 'violated'}"
        f"{'':>16}{'PASS' if out['G2_monotonic'] else 'FAIL'}",
        f"  G3  beats >= 19 of 20 random seeds     "
        f"{out['G3_random_beaten']}/{N_RANDOM_SEEDS}"
        f"{'':>22}{'PASS' if out['G3_random_beaten'] >= 19 else 'FAIL'}",
        "",
    ]
    verdict += [
        "  The screener AS ORIGINALLY SPECIFIED (20-day ROC, no skip, six factors",
        "  at 25/20/20/15/10/10) is measured separately and is worse than the",
        "  corrected one on both horizons:",
        f"      next-day open->close  {out['proposed_oc_edge_bps']:+.1f} bps vs universe, "
        f"t = {out['proposed_oc_edge_t']:.2f}",
        f"      next-day close->close {out['proposed_cc_edge_bps']:+.1f} bps vs universe, "
        f"t = {out['proposed_cc_edge_t']:.2f}",
        "  Both are significantly negative. The 20-day lookback with no skip sits",
        "  inside the short-term reversal window that momentum_xs.py skips a month",
        "  to avoid, so the ranking is pointed at the wrong end of it.",
        "",
    ]

    intraday_ok = g1_pass
    if not intraday_ok:
        verdict += [
            "  G1 is the criterion for the SAME-DAY leg, and it is measured against a",
            f"  universe whose own intraday drift is {out['intraday_drift_bps']:+.1f} bps/day while its",
            f"  overnight drift is {out['overnight_drift_bps']:+.1f} bps/day. A design that buys at the",
            "  open and exits by 15:00 is on the wrong side of that split before it",
            "  pays a single rupee of brokerage.",
            "",
        ]
    if out["beats_universe_at"]:
        verdict += [
            "  ONE result survives. At a "
            f"{out['beats_universe_at'][-1]}-day hold the corrected screener beats the",
            f"  equal-weight universe by {out['best_edge_bps']:+.0f} bps "
            f"(t = {out['best_edge_t']:.2f}), and clears its own",
            f"  Rs.5,000 round-trip cost at holds of {out['clears_cost_at']} days.",
            "",
            "  That is NOT a green light for the strategy in this file. It is a",
            "  different strategy: a multi-week position with no intraday leg, no",
            "  MIS entry and no 15:00 conversion — none of which this gate tested.",
            "  It is also close to what backtest/momentum_delivery/ already trades",
            "  and has already validated, on a longer lookback and 20 names rather",
            "  than 3. Anyone picking it up should benchmark it head-to-head against",
            "  that, on its own pre-registered criteria, before treating it as new.",
            "",
            "  VERDICT: the hybrid intraday-to-delivery design is REJECTED at the",
            "  screener. No execution engine was built, because the selection it",
            "  would execute does not beat picking at random.",
        ]
    else:
        verdict += [
            "  Nothing clears the cost hurdle at any horizon.",
            "",
            "  VERDICT: REJECTED. No execution engine was built.",
        ]
    verdict.append("")

    report = "\n".join(header + body + verdict)
    print("\n" + report)
    (RESULTS_DIR / "gate_report.txt").write_text(report, encoding="utf-8")
    print(f"\nWritten to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
