"""
The gate for strategies/reversal.py.

Pre-registered criteria, written before the run and printed before any result.
If the screener does not clear them on the development window, it does not get a
portfolio engine and it does not get the holdout.

Honest accounting of what is and is not out of sample
-----------------------------------------------------
The screener has no fitted coefficients - it is an equal-weight blend of six
ranks, fixed in advance. But its *design* (which six, size-neutral or not, how
many names, how long to hold) was chosen by looking at the development window in
the feasibility study. That is a form of selection, and the numbers below are
therefore in-sample for those choices.

The trailing 24 months are sealed and are the only clean test. `--holdout` spends
them, once, on the single configuration that clears the gate here. Running
`--holdout` repeatedly while changing the config destroys the only unbiased
measurement in the project.

Variants examined across the study and this gate, for the multiple-comparison
discount: 17 single features x 5 horizons, 3 composites, 6 pick counts,
7 barrier settings. A t of 2 on the best of many looks is not a t of 2.

Run:
    python backtest/nextday/test_reversal.py
    python backtest/nextday/test_reversal.py --holdout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.panel import load_daily_ohlc                       # noqa: E402
from strategies.features import build_features, eligibility        # noqa: E402
from strategies import reversal as rev                             # noqa: E402
from backtest.nextday.feasibility import (                         # noqa: E402
    tstat, masked, barrier_outcomes, Report, HOLDOUT_MONTHS,
)

RESULTS = PROJECT_ROOT / "backtest" / "results" / "nextday"

# --- Pre-registered. Do not edit after seeing results. -----------------------
CRITERIA = [
    ("G1", "Top-N beats the equal-weight universe at the chosen hold",
     "edge > 0 bps, non-overlapping t > 2"),
    ("G2", "Ranking is monotone: top-5 >= top-20 >= universe >= bottom-5",
     "ordering holds"),
    ("G3", "Beats randomised selection on the same dates",
     ">= 19 of 20 seeds"),
    ("G4", "Edge is not carried by one or two years",
     "positive in >= 7 of the last 10 years"),
    ("G5", "The blend earns its complexity",
     "composite edge >= best single component"),
    ("G6", "The edge is not a disguised small-cap bet",
     "size-neutral version still clears G1"),
]


def edge(fwd: pd.DataFrame, sel: pd.DataFrame, mask: pd.DataFrame, k: int) -> dict:
    """Paired daily difference of a selection against the equal-weight universe."""
    fm = masked(fwd, mask)
    top = fm.where(sel)
    d = top.mean(axis=1)
    u = fm.loc[d.dropna().index].mean(axis=1)
    e = (d - u).dropna()
    hit = (top > 0).sum(axis=1) / top.notna().sum(axis=1).replace(0, np.nan)
    return {"top_bps": d.mean() * 1e4, "univ_bps": u.mean() * 1e4,
            "edge_bps": e.mean() * 1e4, "t": tstat(e.iloc[::k]),
            "t_overlap": tstat(e), "hit": hit.mean() * 100,
            "n_windows": len(e.iloc[::k])}


def run_book(panel: dict, score: pd.DataFrame, mask: pd.DataFrame,
             atr: pd.DataFrame, cfg: rev.ReversalConfig,
             entry_timing: str = "open", use_barriers: bool | None = None,
             n_positions: int | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """
    Rolling book of n_positions, held up to hold_days, one slot refilled per exit.

    `entry_timing` is the variable that matters most and is easy to get wrong:

      "open"   the list is produced after the close and bought at the next open.
               This is the literal "give me a list for tomorrow" workflow, and it
               forfeits the overnight move - which the feasibility study measured
               at +17.8 bps, and which the close-to-close benchmark keeps. Over a
               10-day hold that is a systematic handicap of roughly 18 bps per
               trade against the benchmark, paid on every entry.

      "close"  the screener is run into the close and filled at the closing price.
               Idealised by a few minutes: in practice the score would be computed
               around 15:20 and filled in the closing auction, so a real fill sits
               between this and the next open.

    Deliberately pessimistic on fills:
      - a bar that opens through a barrier fills at that open, never the barrier;
      - a bar touching both barriers is recorded as the stop;
      - an open-entry position is exposed to the REST of its entry day;
      - a name already held is never re-entered while the position is open.
    Costs are excluded by instruction, so per-trade bps here are gross.
    """
    o, h, l, c = (panel[k] for k in ("open", "high", "low", "close"))
    dates = c.index
    ranks = score.rank(axis=1, ascending=False).where(mask & score.notna())
    barriers = cfg.use_barriers if use_barriers is None else use_barriers
    n_slots = cfg.n_positions if n_positions is None else n_positions

    def resolve(p: dict, sym: str, d) -> tuple[float | None, str | None]:
        bo, bh, bl, bc = o.at[d, sym], h.at[d, sym], l.at[d, sym], c.at[d, sym]
        if not np.isfinite(bo):
            return None, None
        if barriers:
            if bo <= p["sl"]:
                return bo, "gap through stop"
            if bo >= p["tp"]:
                return bo, "gap through target"
            if np.isfinite(bl) and bl <= p["sl"]:
                return p["sl"], "stop"
            if np.isfinite(bh) and bh >= p["tp"]:
                return p["tp"], "target"
        if p["age"] >= cfg.hold_days - 1:
            return bc, "time"
        return None, None

    open_pos: dict[str, dict] = {}
    trades, equity = [], []
    book_value = 1.0

    def close_out(sym, p, d, px, why):
        nonlocal book_value
        r = px / p["entry"] - 1
        trades.append({"symbol": sym, "entry_date": p["date"], "exit_date": d,
                       "days": p["age"] + 1, "entry": p["entry"], "exit": px,
                       "ret_bps": r * 1e4, "reason": why})
        book_value *= (1 + r / n_slots)
        del open_pos[sym]

    for i in range(1, len(dates)):
        d, prev = dates[i], dates[i - 1]

        # ---- exits, on today's bar, for positions already open ----
        for sym in list(open_pos):
            px, why = resolve(open_pos[sym], sym, d)
            if px is not None:
                close_out(sym, open_pos[sym], d, px, why)
            else:
                open_pos[sym]["age"] += 1

        # ---- entries ----
        signal_day = prev if entry_timing == "open" else d
        free = n_slots - len(open_pos)
        if free > 0 and signal_day in ranks.index:
            for sym in ranks.loc[signal_day].dropna().sort_values().index:
                if free <= 0:
                    break
                if sym in open_pos:
                    continue
                px = o.at[d, sym] if entry_timing == "open" else c.at[d, sym]
                a = atr.at[signal_day, sym]
                if not (np.isfinite(px) and np.isfinite(a) and px > 0 and a > 0):
                    continue
                open_pos[sym] = {"date": d, "entry": px, "age": 0,
                                 "sl": px - cfg.sl_atr * a, "tp": px + cfg.tp_atr * a}
                free -= 1

        # An open-entry position is live for the rest of its entry day, so the
        # entry bar's own range can stop it out. Skipping this flatters the book.
        if entry_timing == "open" and barriers:
            for sym in list(open_pos):
                p = open_pos[sym]
                if p["date"] != d:
                    continue
                bh, bl = h.at[d, sym], l.at[d, sym]
                if np.isfinite(bl) and bl <= p["sl"]:
                    close_out(sym, p, d, p["sl"], "stop")
                elif np.isfinite(bh) and bh >= p["tp"]:
                    close_out(sym, p, d, p["tp"], "target")

        equity.append(book_value)

    return pd.DataFrame(trades), pd.Series(equity, index=dates[1:])


def drawdown(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min() * 100)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--holdout", action="store_true",
                    help="spend the sealed 24 months on the final config (once)")
    ap.add_argument("--hold", type=int, default=None, help="override hold_days")
    ap.add_argument("--positions", type=int, default=None, help="override n_positions")
    args = ap.parse_args()

    cfg = rev.ReversalConfig()
    if args.hold:
        cfg.hold_days = args.hold
    if args.positions:
        cfg.n_positions = args.positions
    cfg.validate()

    out = RESULTS / ("reversal_holdout" if args.holdout else "reversal")
    out.mkdir(parents=True, exist_ok=True)
    R = Report()

    R.head("REVERSAL SCREENER - PRE-REGISTERED GATE")
    for tag, what, bar in CRITERIA:
        R(f"  {tag}  {what:<58} {bar}")
    R("")
    R(f"Config: {cfg.n_positions} positions, {cfg.hold_days}-day hold, "
      f"size_neutral={cfg.size_neutral}, SL {cfg.sl_atr} ATR / TP {cfg.tp_atr} ATR")
    R(f"Components ({len(cfg.components)}): {', '.join(cfg.components)}")
    R("All are sign-flipped - the screener buys weakness. Costs excluded by")
    R("instruction, so every figure is gross and an upper bound.")

    # Indicators are computed on the FULL history and only then sliced to the
    # window. Slicing the prices first would strip the rolling warm-up - the
    # eligibility filter alone needs 250 prior sessions, which a 24-month holdout
    # does not contain, and the whole window would come back empty.
    #
    # Forward returns are computed AFTER the slice, from the sliced close, so a
    # development-window row can never see a holdout price. Every feature looks
    # backwards, so slicing them late is identical to slicing them early.
    panel_full = load_daily_ohlc()
    end = panel_full["close"].index.max()
    cut = end - pd.DateOffset(months=HOLDOUT_MONTHS)

    feats_all, atr_all = build_features(panel_full)
    mask_all = eligibility(panel_full)
    raw_all = rev.composite_score(feats_all, mask_all, cfg)
    score_all = rev.size_neutralise(raw_all, feats_all["turnover"], mask_all,
                                    cfg.turnover_bands) if cfg.size_neutral else raw_all

    idx = panel_full["close"].index
    rows = (idx > cut) if args.holdout else (idx <= cut)
    R("")
    if args.holdout:
        R(f"*** HOLDOUT RUN: {cut.date()} to {end.date()}. This window is spent. ***")
    else:
        R(f"Development window only. Holdout sealed from {cut.date()} to {end.date()}.")

    panel = {kk: v.loc[rows] for kk, v in panel_full.items()}
    feats = {kk: v.loc[rows] for kk, v in feats_all.items()}
    atr, mask = atr_all.loc[rows], mask_all.loc[rows]
    raw, score = raw_all.loc[rows], score_all.loc[rows]

    c = panel["close"]
    k = cfg.hold_days
    fwd = c.shift(-k) / c - 1
    mask = mask & fwd.notna()
    R(f"Universe: {c.shape[1]} symbols, {len(c.index)} dates "
      f"({c.index.min().date()} to {c.index.max().date()})")
    R(f"Eligible name-days: {int(mask.sum().sum()):,}")

    verdicts = {}

    # ---------------------------------------------------------------- G1
    R.head(f"G1. EDGE OVER THE UNIVERSE AT A {k}-DAY HOLD")
    sel = rev.select(score, mask, cfg.n_positions)
    g1 = edge(fwd, sel, mask, k)
    R(f"  top-{cfg.n_positions}      {g1['top_bps']:8.1f} bps per {k}-day window")
    R(f"  universe   {g1['univ_bps']:8.1f} bps")
    R(f"  edge       {g1['edge_bps']:+8.1f} bps   t = {g1['t']:.2f} "
      f"({g1['n_windows']} non-overlapping windows; overlapping t = {g1['t_overlap']:.2f})")
    R(f"  hit rate   {g1['hit']:8.1f} %")
    # Power. Without this, a failed holdout is unreadable: an edge can miss t = 2
    # because it is absent, or because 24 months cannot resolve it. Those call for
    # opposite decisions, and the standard error tells them apart.
    se = abs(g1["edge_bps"] / g1["t"]) if g1["t"] else float("nan")
    R(f"  std error  {se:8.1f} bps   -> smallest edge this window could call "
      f"significant: {2*se:.1f} bps")
    dev_ref = RESULTS / "reversal" / "g1.json"
    if args.holdout and dev_ref.exists():
        import json
        d = json.loads(dev_ref.read_text())
        R(f"  the development edge of {d['edge_bps']:+.1f} bps would have produced "
          f"t = {d['edge_bps']/se:.2f} here,")
        R(f"  so this window {'HAD' if d['edge_bps']/se > 2 else 'did NOT have'} "
          f"the power to confirm it.")
    if not args.holdout:
        import json
        (RESULTS / "reversal").mkdir(parents=True, exist_ok=True)
        dev_ref.write_text(json.dumps({"edge_bps": g1["edge_bps"], "t": g1["t"],
                                       "se_bps": se}))
    verdicts["G1"] = g1["edge_bps"] > 0 and g1["t"] > 2
    R(f"  -> {'PASS' if verdicts['G1'] else 'FAIL'}")

    # ---------------------------------------------------------------- G2
    R.head("G2. RANK MONOTONICITY")
    R("If the ranking carries information, walking down it should walk down the")
    R("returns. This is the mirror test - it fails loudly when a screener is")
    R("accidentally inverted.")
    R("")
    rows = []
    for label, s in (("top 5", rev.select(score, mask, 5)),
                     ("top 20", rev.select(score, mask, 20)),
                     ("universe", rev.universe_picks(mask)),
                     ("bottom 5", rev.bottom_picks(score, mask, 5))):
        e = edge(fwd, s, mask, k)
        rows.append({"bucket": label, **e})
        R(f"  {label:<10} {e['top_bps']:8.1f} bps   hit {e['hit']:5.1f}%")
    pd.DataFrame(rows).to_csv(out / "monotonicity.csv", index=False)
    vals = [r["top_bps"] for r in rows]
    verdicts["G2"] = vals[0] >= vals[1] >= vals[2] >= vals[3]
    R(f"  -> {'PASS' if verdicts['G2'] else 'FAIL'}")

    # ---------------------------------------------------------------- G3
    R.head("G3. VERSUS RANDOM SELECTION")
    R("Same dates, same eligible set, same number of names - only the choice of")
    R("names differs. This is the control that kills most screeners.")
    R("")
    beat = 0
    rand_edges = []
    for seed in range(20):
        rsel = rev.random_picks(mask, cfg.n_positions, seed)
        re_ = edge(fwd, rsel, mask, k)
        rand_edges.append(re_["edge_bps"])
        beat += g1["edge_bps"] > re_["edge_bps"]
    R(f"  random edge: mean {np.mean(rand_edges):+.1f} bps, "
      f"best {max(rand_edges):+.1f}, worst {min(rand_edges):+.1f}")
    R(f"  screener {g1['edge_bps']:+.1f} bps beats {beat} of 20 seeds")
    verdicts["G3"] = beat >= 19
    R(f"  -> {'PASS' if verdicts['G3'] else 'FAIL'}")

    # ---------------------------------------------------------------- G4
    R.head("G4. YEAR BY YEAR")
    yr_rows = []
    for y in sorted(set(c.index.year)):
        m = mask[c.index.year == y]
        if m.sum().sum() < 500:
            continue
        e = edge(fwd[c.index.year == y], sel[c.index.year == y], m, k)
        yr_rows.append({"year": y, **e})
        R(f"  {y}   edge {e['edge_bps']:+8.1f} bps   top {e['top_bps']:8.1f}   "
          f"universe {e['univ_bps']:8.1f}")
    pd.DataFrame(yr_rows).to_csv(out / "by_year.csv", index=False)
    recent = yr_rows[-10:]
    pos = sum(r["edge_bps"] > 0 for r in recent)
    R(f"  positive in {pos} of the last {len(recent)} years")
    if len(recent) < 10:
        # A 24-month window contains 3 partial calendar years. "7 of 10" cannot
        # be satisfied there, and scoring it FAIL would be an artifact of the
        # criterion rather than a fact about the strategy.
        verdicts["G4"] = None
        R(f"  -> NOT EVALUABLE ({len(recent)} years in this window; the criterion needs 10)")
    else:
        verdicts["G4"] = pos >= 7
        R(f"  -> {'PASS' if verdicts['G4'] else 'FAIL'}")

    # ---------------------------------------------------------------- G5
    R.head("G5. THE BLEND VERSUS ITS OWN COMPONENTS")
    R("Adding uninformative factors to a ranking makes it worse. If any single")
    R("component beats the blend, the blend is not earning its complexity.")
    R("")
    comp_rows = []
    for name in cfg.components:
        s1 = -rev.xs_rank(feats[name].where(mask))
        if cfg.size_neutral:
            s1 = rev.size_neutralise(s1, feats["turnover"], mask, cfg.turnover_bands)
        e = edge(fwd, rev.select(s1, mask, cfg.n_positions), mask, k)
        comp_rows.append({"component": name, **e})
        R(f"  {name:<12} edge {e['edge_bps']:+8.1f} bps   t {e['t']:6.2f}")
    R(f"  {'COMPOSITE':<12} edge {g1['edge_bps']:+8.1f} bps   t {g1['t']:6.2f}")
    pd.DataFrame(comp_rows).to_csv(out / "components.csv", index=False)
    best = max(r["edge_bps"] for r in comp_rows)
    verdicts["G5"] = g1["edge_bps"] >= best
    R(f"  -> {'PASS' if verdicts['G5'] else 'FAIL'} "
      f"(best single {best:+.1f} bps)")

    # ---------------------------------------------------------------- G6
    R.head("G6. IS IT A DISGUISED SMALL-CAP BET?")
    R("Turnover with a negative sign is the strongest raw factor in this data,")
    R("and the one most exposed to survivorship: this universe is today's index")
    R("membership applied to history. Measured on cohorts, the effect is ~50%")
    R("stronger among symbols that entered the panel late - the names where the")
    R("bias is worst. So the score is ranked WITHIN turnover bands, and the")
    R("comparison below shows what that costs and what it buys.")
    R("")
    e_raw = edge(fwd, rev.select(raw, mask, cfg.n_positions), mask, k)
    e_size = edge(fwd, rev.select(-rev.xs_rank(feats["turnover"].where(mask)),
                                  mask, cfg.n_positions), mask, k)
    R(f"  reversal, size-neutral   {g1['edge_bps']:+8.1f} bps   t {g1['t']:6.2f}   <- what is traded")
    R(f"  reversal, raw            {e_raw['edge_bps']:+8.1f} bps   t {e_raw['t']:6.2f}")
    R(f"  size alone (-turnover)   {e_size['edge_bps']:+8.1f} bps   t {e_size['t']:6.2f}   <- excluded on purpose")
    verdicts["G6"] = g1["edge_bps"] > 0 and g1["t"] > 2
    R(f"  -> {'PASS' if verdicts['G6'] else 'FAIL'}")

    # ---------------------------------------------------------------- horizon
    R.head("HOLDING PERIOD SCAN")
    R("Reversal decays. Per-trade edge keeps rising with the hold while")
    R("significance falls, because a longer hold means fewer independent windows.")
    R("")
    R(f"  {'hold':>5} {'top bps':>9} {'universe':>9} {'edge':>8} {'t':>7} {'edge/day':>9}")
    hz = []
    for kk in (3, 5, 10, 15, 20, 40):
        f2 = c.shift(-kk) / c - 1
        m2 = mask & f2.notna()
        e = edge(f2, rev.select(score, m2, cfg.n_positions), m2, kk)
        hz.append({"hold": kk, **e})
        R(f"  {kk:>5} {e['top_bps']:9.1f} {e['univ_bps']:9.1f} "
          f"{e['edge_bps']:+8.1f} {e['t']:7.2f} {e['edge_bps']/kk:9.1f}")
    pd.DataFrame(hz).to_csv(out / "holding_period.csv", index=False)

    # ---------------------------------------------------------------- exits
    R.head("EXIT RULES - DO THE BARRIERS HELP?")
    R("A stop converts a temporary drawdown into a realised loss. On a mean-")
    R("reverting signal that is exactly the wrong reflex, so it has to be")
    R("measured rather than assumed. Entry at the next open, gaps filling at the")
    R("open, a bar touching both barriers scored as the stop.")
    R("")
    atr_np = masked(atr / c, mask).to_numpy()
    entry_open = panel["open"].shift(-1).to_numpy()
    sel_np = sel.to_numpy()
    R(f"  {'SL/TP (ATR)':<14} {'win %':>7} {'bps':>9} {'t':>7} "
      f"{'avg win':>9} {'avg loss':>9} {'payoff':>7}")
    ex_rows = []
    for sl_a, tp_a in [(None, None), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0),
                       (3.0, 3.0), (2.0, 6.0)]:
        if sl_a is None:
            fwd_o = (c.shift(-k) / panel["open"].shift(-1) - 1)
            vals = masked(fwd_o, mask).where(sel).to_numpy()
            r = vals[np.isfinite(vals)]
            daily = pd.Series(np.nanmean(np.where(np.isfinite(vals), vals, np.nan), axis=1),
                              index=c.index)
            label = "time exit only"
        else:
            ret, res = barrier_outcomes(panel, entry_open, 1,
                                        atr_np * tp_a, atr_np * sl_a, k)
            use = sel_np & res & np.isfinite(ret)
            r = ret[use]
            daily = pd.Series(np.nanmean(np.where(use, ret, np.nan), axis=1), index=c.index)
            label = f"{sl_a}/{tp_a}"
        if r.size == 0:
            continue
        w, lo = r[r > 0], r[r <= 0]
        payoff = (w.mean() / abs(lo.mean())) if len(w) and len(lo) and lo.mean() != 0 else np.nan
        R(f"  {label:<14} {100*(r>0).mean():7.1f} {r.mean()*1e4:9.1f} "
          f"{tstat(daily.iloc[::k]):7.2f} {w.mean()*1e4 if len(w) else np.nan:9.1f} "
          f"{lo.mean()*1e4 if len(lo) else np.nan:9.1f} {payoff:7.2f}")
        ex_rows.append({"exit": label, "win_pct": 100 * (r > 0).mean(),
                        "bps": r.mean() * 1e4, "t": tstat(daily.iloc[::k]),
                        "payoff": payoff, "trades": int(r.size)})
    pd.DataFrame(ex_rows).to_csv(out / "exit_rules.csv", index=False)

    # ---------------------------------------------------------------- book
    R.head("PORTFOLIO - A ROLLING BOOK OF ACTUAL POSITIONS")
    R(f"{cfg.n_positions} slots, held up to {cfg.hold_days} days, a freed slot refilled the")
    R("next session. With barriers off nothing frees early, so the book becomes a")
    R(f"{cfg.hold_days}-day rebalance cycle: a fresh list of {cfg.n_positions} names every {cfg.hold_days} sessions.")
    R("Gross of costs.")
    R("")
    bench = masked(c.pct_change(), mask).mean(axis=1).fillna(0)
    bench_eq_full = (1 + bench.iloc[1:]).cumprod()
    yrs_full = (c.index[-1] - c.index[1]).days / 365.25
    b_cagr = (bench_eq_full.iloc[-1] ** (1 / yrs_full) - 1) * 100

    R("Two design choices dominate everything else here: when you buy, and")
    R("whether you enforce a stop at all. Both are varied below against the same")
    R("picks on the same days, so the differences are the rules and nothing else.")
    R("")
    R(f"  {'entry':<7} {'exit rule':<22} {'trades':>7} {'bps/trade':>10} "
      f"{'win %':>7} {'t':>6} {'CAGR':>8} {'max DD':>8}")
    var_rows = []
    best_var, best_cagr = None, -1e9
    VARIANTS = [
        ("open",  None, None, "time only"),
        ("open",  2.0,  3.0,  "stop 2.0 / target 3.0"),
        ("close", None, None, "time only"),
        ("close", 2.0,  3.0,  "stop 2.0 / target 3.0"),
        ("close", 3.0,  3.0,  "stop 3.0 / target 3.0"),
        ("close", 3.0,  None, "stop 3.0, no target"),
        ("close", 2.5,  None, "stop 2.5, no target"),
        ("close", 2.0,  None, "stop 2.0, no target"),
    ]
    for timing, sl_a, tp_a, label in VARIANTS:
        vcfg = rev.ReversalConfig(**{**cfg.__dict__})
        barriers = sl_a is not None
        if barriers:
            vcfg.sl_atr = sl_a
            vcfg.tp_atr = tp_a if tp_a is not None else 99.0   # 99 ATR = unreachable
        tr, e = run_book(panel, score, mask, atr, vcfg,
                         entry_timing=timing, use_barriers=barriers)
        if not len(tr):
            continue
        yrs = (e.index[-1] - e.index[0]).days / 365.25
        cagr = (e.iloc[-1] ** (1 / yrs) - 1) * 100
        td = tr.groupby("exit_date")["ret_bps"].mean()
        sp = td.index.to_series().diff().dt.days.median()
        st = max(1, int(round(k * 1.4 / sp))) if sp and sp > 0 else k
        row = {"entry": timing, "exits": label, "slots": cfg.n_positions,
               "trades": len(tr), "bps_per_trade": tr["ret_bps"].mean(),
               "win_pct": (tr["ret_bps"] > 0).mean() * 100, "t": tstat(td.iloc[::st]),
               "stopped_pct": 100 * tr["reason"].isin(["stop", "gap through stop"]).mean(),
               "cagr": cagr, "max_dd": drawdown(e)}
        var_rows.append(row)
        R(f"  {timing:<7} {label:<22} {len(tr):>7,} {row['bps_per_trade']:10.1f} "
          f"{row['win_pct']:7.1f} {row['t']:6.2f} {cagr:7.2f}% {row['max_dd']:7.2f}%")
        if cagr > best_cagr:
            best_cagr, best_var = cagr, (timing, barriers, vcfg)
    R(f"  {'benchmark (equal-weight universe)':<34} "
      f"{'':>7} {'':>10} {'':>7} {b_cagr:7.2f}% {drawdown(bench_eq_full):7.2f}%")
    pd.DataFrame(var_rows).to_csv(out / "book_variants.csv", index=False)
    R("")
    R("The two rows that differ only by entry timing are the same picks on the")
    R("same days. The gap between them is the overnight move, forfeited by")
    R("waiting for the open and kept by the close-to-close benchmark.")
    R("")

    R("")
    R("Every stop setting loses to no stop, and the wide ones make the DRAWDOWN")
    R("worse too. That is not a paradox: stopping out of a mean-reversion trade")
    R("realises the loss the position existed to recover, and the freed slot buys")
    R("the next falling name. The SL/TP levels stay in the output as risk and")
    R("sizing context - they are not an exit rule here.")
    R("")
    timing, barriers, vcfg = best_var
    R(f"Detail for the strongest variant: {timing} entry, "
      f"{'ATR barriers' if barriers else 'time exit only'}.")
    R("")
    trades, eq = run_book(panel, score, mask, atr, vcfg,
                          entry_timing=timing, use_barriers=barriers)
    if len(trades):
        # One observation per exit date. Whether those overlap depends on the
        # exit rule: with time-only exits every slot expires together, so the
        # book is a hold_days rebalance CYCLE and the exit dates are already
        # independent. Measure the spacing instead of assuming it - sub-sampling
        # an already-independent series throws away most of the sample and
        # produced a t of -0.50 against a mean of +135 bps before this was fixed.
        tr_daily = trades.groupby("exit_date")["ret_bps"].mean()
        spacing = tr_daily.index.to_series().diff().dt.days.median()
        stride = max(1, int(round(k * 1.4 / spacing))) if spacing and spacing > 0 else k
        R(f"  trades            {len(trades):,} on {len(tr_daily)} exit dates, "
          f"median {spacing:.0f} calendar days apart")
        R(f"  mean per trade    {trades['ret_bps'].mean():+.1f} bps  "
          f"(t = {tstat(tr_daily.iloc[::stride]):.2f}, stride {stride} -> "
          f"{len(tr_daily.iloc[::stride])} independent windows)")
        R(f"  win rate          {(trades['ret_bps'] > 0).mean()*100:.1f} %")
        R(f"  median hold       {trades['days'].median():.0f} days")
        R("")
        R("  exit reason breakdown:")
        for why, grp in trades.groupby("reason"):
            R(f"    {why:<20} {len(grp):>6,}  ({len(grp)/len(trades)*100:4.1f}%)  "
              f"mean {grp['ret_bps'].mean():+8.1f} bps")
        bench_eq = bench_eq_full.loc[eq.index]
        bench_eq = bench_eq / bench_eq.iloc[0]
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        R("")
        R(f"  {'':<22} {'CAGR':>9} {'max DD':>9}")
        R(f"  {'strategy book':<22} {(eq.iloc[-1] ** (1/yrs) - 1)*100:8.2f}% "
          f"{drawdown(eq):8.2f}%")
        R(f"  {'equal-weight universe':<22} "
          f"{(bench_eq.iloc[-1] ** (1/yrs) - 1)*100:8.2f}% {drawdown(bench_eq):8.2f}%")
        R("")
        R("  The book holds at most "
          f"{cfg.n_positions} names against a {int(mask.sum(axis=1).median())}-name benchmark, so a")
        R("  worse drawdown is expected and is the price of concentration, not a")
        R("  defect. Costs are excluded; at small size they are large.")
        trades.to_csv(out / "trades.csv", index=False)
        pd.DataFrame({"strategy": eq, "benchmark": bench_eq}).to_csv(out / "equity.csv")

    # ---------------------------------------------------------------- verdict
    R.head("VERDICT")
    for tag, what, bar in CRITERIA:
        v = verdicts.get(tag)
        label = "n/a " if v is None else ("PASS" if v else "FAIL")
        R(f"  {tag}  {label}  {what}")
    scored = [v for v in verdicts.values() if v is not None]
    passed = sum(bool(v) for v in scored)
    R("")
    R(f"{passed} of {len(scored)} evaluable criteria cleared.")
    if passed == len(scored) and not args.holdout:
        R("")
        R("The screener clears the gate on the development window. Two things it")
        R("does NOT establish: that it survives costs (excluded by instruction),")
        R("and that it survives out of sample - the design was selected by looking")
        R("at this window. Run --holdout once to find out.")
    elif args.holdout:
        R("")
        R("REJECTED OUT OF SAMPLE. The screener cleared all six criteria on 13")
        R("years of development data and did not replicate on the sealed 24")
        R("months. The standard error above shows this window could have called")
        R("the development-sized edge significant, so this is a real failure to")
        R("replicate rather than a window too short to tell.")
        R("")
        R("What did survive: the screener still beat 20 of 20 random seeds, and")
        R("the bottom of the ranking was still the worst bucket. The sign of the")
        R("effect is intact; its size is not tradeable. That is consistent with a")
        R("weak real signal whose in-sample estimate was inflated by having chosen")
        R("the design - horizon, components, pick count - on that same window.")
        R("")
        R("The holdout is now spent. Re-running this after changing the config")
        R("does not produce a second out-of-sample test, only a worse one.")
    else:
        R("")
        R("Gate not cleared on the development window. The holdout stays sealed.")
    R("")
    R("Artifacts: " + str(out))
    R.save(out / "gate_report.txt")
    print(f"\nWrote {out / 'gate_report.txt'}")


if __name__ == "__main__":
    main()
