# Hybrid Intraday-to-Delivery Momentum — build plan and outcome

## OUTCOME: rejected at the screener (2026-08-23)

The plan below was executed as far as its own gate, and the gate's pre-registered
kill criterion fired. **No execution engine was built.** What exists:

| File | Status |
|---|---|
| `backtest/costs.py` | extended — `hybrid_round_trip()`, `net_levels()`, and a 2026 intraday schedule calibrated to a real contract note |
| `strategies/hybrid_momentum.py` | built, marked REJECTED in its docstring |
| `backtest/hybrid_momentum/test_screener_gate.py` | built and run — this is the result |
| `backtest/results/hybrid_momentum/` | `gate_report.txt` + 6 CSVs |
| `test_hybrid.py`, `test_delivery_arm.py`, `analysis.py` | **not built** — the gate failed |
| `README.md` | Part 3 added |

Gate result, development window with the 24-month holdout sealed:

| # | Criterion | Result | |
|---|---|---|---|
| G1 | Next-day open→close edge over universe > 0, t > 2 | −6.2 bps, t = −2.55 | **FAIL** |
| G2 | Rank monotone top-1 ≥ top-3 ≥ universe ≥ bottom-3 | bottom-3 (+9.8) > top-3 (+8.6) > universe (+7.8) | **FAIL** |
| G3 | Beats ≥ 19 of 20 random seeds | 8/20 | **FAIL** |

The design *exactly as originally specified* scored worse than the corrected one:
−11.1 bps vs the universe on open→close (t = −4.18), −6.2 bps on close→close
(t = −2.23), underperforming equal-weighting at every hold from 1 to 20 days.

**One result survived** and is not this strategy: at a 40-day hold the corrected
screener beats the universe by +117 bps (t = 2.55, non-overlapping). That is a
multi-week position with no intraday leg and no conversion, and it sits close to
what `momentum_delivery/` already trades and has validated. It would need its own
pre-registered head-to-head before being treated as a new finding.

### Branch scoping

`intra-multi` was subsequently reduced to this strategy alone. The intraday
gap/ORB family, the EMA-pullback family, the delivery-momentum work and the
live/paper-trading pipeline were removed from this branch; all of them remain on
`main` and `intra-faiz`, which was verified before deleting. Consequences:

- `backtest/portfolio.py` went with the momentum work, so `HOLDOUT_MONTHS` is
  inlined in the gate rather than imported. The value (24) is unchanged, so the
  two branches stay comparable.
- `data/corporate_actions.py`'s `__main__` block imported `portfolio.load_daily`
  and would have crashed. It now uses `hybrid_momentum.load_daily_ohlc`.
- `backtesting` and `bokeh` were dropped from `requirements.txt`; nothing left
  here imports them.
- The CI workflow's strategy list pointed at four deleted scripts and now offers
  the three that survive.

### Corrections to the numbers in the plan below

The plan's Context section was written from an exploratory pass that computed
t-stats across *name-days* on *overlapping* windows. Both inflate t badly. The
gate computes them across dates on non-overlapping windows, and the honest
figures are materially weaker:

| | Exploratory (wrong) | Gate (honest) |
|---|---|---|
| 60/skip-5 top-3 at d20 | +254 bps, t = 21.0 | +172 bps, t = 3.7 |
| ...as an edge over the universe | — | **+7.9 bps, t = 1.85** |
| 60/skip-5 top-3 at d10 | +124 bps, t = 14.6 | +84 bps vs universe's +85 |
| momentum vs near-high correlation | 0.77 | 0.77 for the *20-day* leg; **−0.05** for the corrected 60/skip-5 leg |
| Hybrid cost at ₹5,000 | 94.8 bps | **103.5 bps** (brokerage rate was also understated) |
| Intraday cost at ₹5,000 | 20.6 bps | **36.3 bps** |

Two cost inputs were settled against the account holder's real charges rather
than a rate card, which resolved manual items 1 and 2 below:

- **DP charge = ₹23.60** per scrip per sell — exactly ₹20 + 18% GST, confirming
  the existing model.
- **Intraday brokerage is `max(₹5, min(₹20, 0.1%))`, not `min(₹20, 0.03%)`.** A
  real round trip (buy ₹4,852 → ₹6.08, sell ₹4,640 → ₹7.07, total ₹13.15) is
  reproduced to the paisa by `intraday_leg_2026()` once STT and stamp duty are
  rounded to whole rupees. The legacy function is untouched so Parts 1 and 2 of
  the README still reproduce; the correction widens Part 1's rejection.

### Still open

- Manual item 1 (does MIS→CNC conversion reclassify the buy leg's STT?) remains
  unverified. It is worth ~10 bps on ₹5,000 and the conservative assumption is
  in force. It stopped mattering once the screener failed, but it would matter
  again for any strategy that converts.
- The gate tests *selection*, not *trade management*. It does not establish that
  SL/TP placement and the conversion rule are worthless in general — only that
  the selection they would act on does not beat random.

---

*Everything below is the plan as approved, kept unedited as the record of what
was intended and what was assumed before the data was seen.*

---


## Context

The goal is a long-only NSE strategy that screens daily, enters MIS at the open with
pre-computed SL/TP, converts profitable positions to CNC at 15:00, and manages the
delivery leg to fixed targets — on ₹5,000 of real capital.

Before planning the build I measured the proposal's core assumptions against the
repo's own committed data (`data/daily/`, 205 symbols × 15 years) and cost model
(`backtest/costs.py`). Six of them are wrong, and three are wrong in ways that
change the design rather than just the numbers:

| Assumption in the proposal | Measured |
|---|---|
| Screener next-day hit rate > 55% | **43.7%** (t = −5.07, n = 3,653) |
| Screener next-day open→close positive | **−23.6 bps** (universe −9.5) |
| Bottom-ranked control symmetrically worse | **better** — −5.4 vs −17.6 bps O→C |
| Hybrid round trip ≈ 25 bps | **84.8–94.8 bps** at ₹5,000; **212.7 bps** split 3 ways |
| Delivery R:R 1:1.67, breakeven 38% | **1.03**, breakeven **49.3%** (1 pos) / **64.1%** (3 pos) |
| Intraday R:R 1:5 | **≈1:1** — risk is `entry − prev_low + 0.3·ATR`, not `0.3·ATR` |

Three structural causes, each of which the build has to answer:

1. **The return lives overnight.** Across 303,872 eligible name-days: prev-close→open
   **+18.4 bps (t = 115.9, hit 63.2%)**, open→close **−9.5 bps (t = −26.1, hit 45.3%)**,
   close→close +8.6 bps. A 09:15 entry with a same-day exit systematically donates the
   only reliable drift in the data and pays a −9.5 bps/day headwind on top of a 20.6 bps toll.
2. **20-day ROC with no skip loads on short-term reversal.** This is the effect
   `strategies/momentum_xs.py` skips a month to avoid ("the most recent month carries
   short-term reversal, which contaminates the momentum signal"). Every factor in the
   proposed screener ranks *worse* than the universe baseline on the next-day intraday leg,
   and `roc20 top1` is the worst of them at −30.7 bps.
3. **Two of six factors carry zero information.** "Relative Strength vs Nifty"
   (20% weight) is `roc20 − index_roc20`; the index term is a per-date constant, so it is
   **rank-identical to `roc20` on 500/500 dates tested** — it cannot reorder anything.
   "Trend Alignment above 50-DMA" (15%) is already a hard filter, so every survivor scores
   the same. Of the remaining four, `roc20`/`near-20d-high` are 0.77 rank-correlated;
   only `volume expansion` is near-orthogonal (0.04).

Repointing the lookback fixes the signal. **60-day ROC skipping the last 5 days**,
top 3, bought at the close and held:

| Hold | 1d | 3d | 5d | 10d | 20d | 40d |
|---|---:|---:|---:|---:|---:|---:|
| roc60-skip5 top3 | +11 | +36 (t 7.5) | +60 (t 10.0) | **+124 (t 14.6)** | **+254 (t 21.0)** | **+516 (t 27.0)** |
| Equal-weight universe | +9 | +25 | +41 | +82 | +158 | +313 |
| Proposed composite top3 | +6 | +10 | +26 | +66 | +147 | +357 |

The proposed composite **underperforms the universe at every horizon through 20 days**.
The fixed construction beats it from day 3 and clears the 103 bps cost hurdle from day 10 —
independently reproducing the README's "short 2–5 day swings are the worst of both worlds."

**Intended outcome:** a corrected screener plus two pre-registered arms — the hybrid
MIS→CNC arm as specified (which documents *why* the intraday leg fails, the way Part 1 of
the README does) and a delivery arm in the multi-week zone the measurement supports.
Both scored against criteria written down before the run.

> The figures above span the full 15 years, including the 24-month holdout. The committed
> gate script must call `portfolio.split_holdout()` and report development-window numbers;
> expect them to shift slightly. The holdout is spent once, at the end, on one config.

---

## Design decisions carried into the build

Confirmed with the user:

- **Both arms** get built, sharing one screener and one gate study.
- **Sizing:** default 1 position; 2 and 3 run as measured variants so the cost damage
  is evidence rather than assertion.
- **Delivery exits:** Arm A (`+5% / −3% / 10-day cap`) and Arm B (`no TP, 50-DMA trail,
  40-day cap`) both pre-registered, both run.

Corrections applied to the screener:

| Proposed | Built |
|---|---|
| Momentum = 20-day ROC, 25% | **60-day ROC skipping 5 days, 45%** |
| RS vs Nifty, 20% | **dropped as a score** (rank-identical). Kept as a *regime filter*: trade only when the equal-weight index is above its own 50-DMA |
| Near 20-day high, 20% | kept, **25%** |
| Above 50-DMA, 15% | **hard filter only**, no weight |
| Volume expansion, 10% | kept, **15%** — the one near-orthogonal factor |
| Low recent volatility, 10% | kept, **15%** |
| Score = weighted 0–100 | **weighted mean of cross-sectional percentile ranks** (`rank(pct=True)`), so no factor's raw scale dominates |

Level calculation, corrected:

- `intra_SL = max(prev_low − 0.3·ATR14, entry − MAX_RISK_ATR·ATR14)` with
  `MAX_RISK_ATR = 1.0`. The cap is what makes risk bounded; without it, risk is
  `entry − prev_low + 0.3·ATR`, which is why the 1:5 claim was ~1:1 in practice.
- `intra_TP = entry + R_MULT · (entry − intra_SL)`, `R_MULT = 1.5`. Expressing TP as a
  multiple of *actual* risk makes R:R a controlled parameter instead of an emergent one.
- Delivery levels unchanged for Arm A; Arm B has no TP.
- Report `risk_per_share`, `rr_ratio` and **net-of-cost** TP/SL for the actual position
  size, not gross.

Other corrections:

- **Screen within the tradeable universe.** Screening 205 and trading the 50 with
  intraday data yields ~224 simulatable entries in 2 years — 15.1% of picks land in the
  50, and silently dropping the other 85% is a selection bias. The hybrid arm screens
  **within the 50**: ~1,488 entries, ~22 eligible names/day. The delivery arm screens all 205.
- **No MIS leverage.** ₹5,000 capital buys at most ₹5,000 of stock, so MIS→CNC conversion
  is always possible. State it — with leverage, conversion would be impossible by construction.
- **Calendar hygiene.** Drop the 6 dates whose cross-sectional coverage collapses
  (2014-08-27 = 1 symbol, 2017-08-31 = 6, 2020-09-04 = 9, 2020-11-14 = 46 Muhurat,
  2022-03-08 = 13, **2025-03-12 = 13, inside the intraday window**). Rule: `coverage >= 100`.
- **No NIFTY index series exists** in `data/` — only `nifty50.json`, a symbol list.
  Build the index as the equal-weight mean of the eligible universe, which is also the
  repo's existing benchmark (`momentum_xs.make_buyhold_signal_fn`).
- **Corporate actions** must be repaired before ranking on trailing returns, for the same
  reason `momentum_xs` does. Reuse `data/corporate_actions.detect_price_steps`.

---

## Files

```
strategies/
  hybrid_momentum.py              [NEW]  screener, levels, controls
backtest/
  costs.py                        [MODIFY] + hybrid_round_trip(), net_levels()
  hybrid_momentum/
    __init__.py                   [NEW]
    test_screener_gate.py         [NEW]  the gate — run and read FIRST
    test_hybrid.py                [NEW]  bar-by-bar MIS→CNC engine
    test_delivery_arm.py          [NEW]  close-entry delivery arm
    analysis.py                   [NEW]  charts, funnel, sensitivity
backtest/results/hybrid_momentum/ [NEW]  outputs
.github/workflows/backtest.yml    [MODIFY] add the 4 new scripts to the choice list
requirements.txt                  [MODIFY] add matplotlib, scipy
README.md                         [MODIFY] new Part 3 section
```

### `strategies/hybrid_momentum.py`

Mirror `strategies/momentum_xs.py` exactly — that file is the house pattern: a
`@dataclass` config, point-in-time scoring functions taking `(panel, asof, cfg)`, and
`make_*_signal_fn` control factories. This module decides **what** and **at what levels**;
it never charges costs or simulates fills.

- `HybridConfig` — lookback 60, skip 5, `n_positions` 1, weights, `max_risk_atr` 1.0,
  `r_mult` 1.5, `delivery_tp/sl`, `max_hold_days`, `regime_filter: bool`.
- `factor_scores(panel, asof, cfg) -> DataFrame` — one column per factor, percentile-ranked.
- `composite_score(...)`, `eligible(...)` (mirror `momentum_xs.eligible`, point-in-time),
  `above_trend(...)`, `market_regime_ok(...)`.
- `compute_levels(panel, symbol, asof, entry_price, cfg) -> dict` — the corrected SL/TP.
- `select(panel, asof, cfg) -> list` and `make_signal_fn`.
- Controls, matching `momentum_xs`: `make_random_signal_fn(seed)`,
  `make_bottom_signal_fn`, `make_buyhold_signal_fn`.
- `load_daily_ohlc(data_dir, repair_corporate_actions=True)` — the panel loader.
  `portfolio.load_daily()` returns only closes and volumes; the screener needs High/Low
  for ATR, the 20-day channel and `prev_low`. Reuse
  `data.corporate_actions.detect_price_steps(closes)` to find the cutoffs, then truncate
  all five frames at the same dates so the repair matches the momentum work exactly.

### `backtest/costs.py` — additive only

Do not touch the existing intraday or delivery functions; the README's published numbers
depend on them. Append:

```python
def hybrid_round_trip(buy_value, sell_value, converted_buy_is_delivery=True,
                      slippage_per_leg=SLIPPAGE_PER_LEG) -> dict
```

MIS-rate brokerage on the buy leg, delivery-rate on the sell leg, DP + delivery STT on
the sell. `converted_buy_is_delivery` is the one genuinely uncertain input — see
**Manual items**; default to the conservative `True`.

```python
def net_levels(entry, tp_pct, sl_pct, shares, cost_fn) -> dict
```

Returns net TP/SL, R:R and breakeven win rate after costs, so no report ever quotes a
gross target. Extend `__main__` with a small-capital table (₹1,667 / ₹2,500 / ₹5,000 /
₹25,000 / ₹50,000) — the existing table starts at ₹10,000 and hides the regime that matters here.

Values this must reproduce (₹5,000, 5 bps/leg):

| Position | MIS | Hybrid (optimistic) | Hybrid (conservative) | CNC | DP+GST alone |
|---|---:|---:|---:|---:|---:|
| ₹1,667 (3-way) | 20.6 | 201.5 | **212.7** | 244.6 | 141.6 |
| ₹2,500 (2-way) | 20.6 | 142.6 | **153.8** | 173.8 | 94.4 |
| ₹5,000 (1 pos) | 20.6 | 83.6 | **94.8** | 103.0 | 47.2 |

Slippage is nearly irrelevant here — 5→0 bps/leg moves the ₹5,000 hybrid only 94.8→84.8 bps.
The cost is almost entirely statutory and exactly known, so the usual "but slippage is
assumed" caveat does not apply to this strategy.

### `backtest/hybrid_momentum/test_screener_gate.py` — build this first

The pre-registered gate. Reproduces every number in the Context section as a committed,
reviewable artifact, on the **development window** via `portfolio.split_holdout()`.

1. Factor rank-correlation matrix + the RS-redundancy proof.
2. Return decomposition: overnight / intraday / full-day, universe-wide.
3. Single-factor and composite next-day edge, with t-stats, vs the universe baseline.
4. Top-1 / top-3 / bottom-3 / random controls — is the ranking monotone in rank?
5. Buy-at-close forward returns at k ∈ {1,3,5,10,20,40} vs the universe.
6. Cost hurdle table by capital and position count.

Writes `gate_report.txt`, `factor_correlations.csv`, `next_day_edge.csv`,
`forward_returns.csv`. **If the corrected screener's edge does not exceed its cost hurdle
here, stop and report that** — do not proceed to the engines. Same discipline that killed
the intraday phase.

### `backtest/hybrid_momentum/test_hybrid.py`

Custom bar-by-bar loop, not `backtesting.py` — that library cannot carry a position across
days under two different cost models. Follow the loop in
`backtest/ema_pullback/test_ema_pullback.py` (`for i in range(1, n)` over 5-min bars using
`strategies.session.session_arrays`).

Per day D, per position:
- Entry at the 09:15 bar open + slippage. Pre-market gap filter uses that same open —
  no look-ahead: the NSE pre-open auction publishes at ~09:08 and *is* the 09:15 open.
  Run a sensitivity variant filling at the 09:20 bar open.
- Fill precedence, pessimistic and explicit:
  1. `bar.open <= SL` → fill at `bar.open` (gapped through; never fill at SL).
  2. `bar.low <= SL and bar.high >= TP` in one bar → **assume SL**.
  3. otherwise SL then TP.
  Never fill outside the bar's range.
- At the **15:00 bar** (present on all 493 days — verified): in profit → convert to CNC,
  charge nothing at conversion; at or below entry → square off at that bar's close,
  charge MIS costs.
- Carried CNC positions: check subsequent days on **5-min bars**, not daily bars. The
  same 50 symbols have intraday data, so this removes the "low ≤ SL and high ≥ TP on the
  same daily bar" ambiguity for free.

Sizing: `floor(alloc / entry)`, skip if `shares < 1` **or if deployed capital < 85% of
allocation** — a ₹4,800 stock bought 1-at-a-time leaves 4% deployed and the fixed ₹20 DP
becomes 400+ bps. Log every skip with its reason; silent skips read as coverage that isn't there.

Reports **bps per trade gross and net** as the headline (size-independent, the repo's
preferred metric) with rupee P&L as the practical footnote, plus t-stats.

### `backtest/hybrid_momentum/test_delivery_arm.py`

The 15-year / 205-symbol arm. Entry at close(D) after the screener runs on D's data,
CNC from the start, Arms A and B both. Reuse `portfolio.summarise()` for CAGR / Sharpe /
max-DD / turnover, and `portfolio.split_holdout()`. Benchmark: equal-weight buy-and-hold
over the identical window — and note `run_portfolio`'s `start`-parameter bug described in
the README, which is exactly the trap here.

### `backtest/hybrid_momentum/analysis.py`

Trade-outcome breakdown (the 6 categories from the proposal), conversion funnel
(screened → entered → converted → hit TP), holding-period histogram, equity + drawdown,
and the parameter sweep as a **robustness surface, not a selection mechanism** — the
README's walk-forward already showed that picking the best in-sample variant *lost* to the
pre-registered baseline by −3.41%/yr. Count every variant tested and carry the Bonferroni
bar. Charts via matplotlib, matching `ema_pullback_analysis.py`.

---

## Pre-registered criteria — write these down before running

Calibrated to what is achievable rather than aspirational, and each stated against the
right baseline. "Beats the universe" is the bar, not "is positive" — a long-only equity
strategy making money proves nothing, the market rises.

| # | Criterion | Bar |
|---|---|---|
| 1 | Screener next-day edge vs equal-weight universe, O→C | > 0 bps, t > 2 |
| 2 | Rank monotonicity: top-1 ≥ top-3 ≥ universe ≥ bottom-3 | ordering holds |
| 3 | Beats ≥ 19 of 20 random-selection seeds | 19/20 |
| 4 | **Hybrid arm** net bps/trade after ₹5,000 costs | > 0, t > 2 |
| 5 | **Delivery arm** net CAGR vs equal-weight buy-and-hold | > +3%/yr, max-DD no worse |
| 6 | Beats the MIS-only baseline (never convert) | yes |
| 7 | Max drawdown on ₹5,000 | < 25% |

**Kill criterion:** if the gate (criteria 1–3) fails, the engines do not get run. If the
hybrid arm fails criterion 4 but the delivery arm passes 5, report the hybrid as rejected
and keep the delivery arm — that split verdict is the most likely outcome given the
measurements above, and it is a legitimate result, not a failure of the exercise.

---

## Verification

```bash
python backtest/costs.py                                  # small-capital table + hybrid
python backtest/hybrid_momentum/test_screener_gate.py     # THE GATE — read before anything else
python backtest/hybrid_momentum/test_hybrid.py            # 2y, 50 symbols, 5-min bars
python backtest/hybrid_momentum/test_delivery_arm.py      # 15y, 205 symbols
python backtest/hybrid_momentum/analysis.py               # charts + sweeps
```

Invariants to assert inside the engines, not just eyeball:

- No fill outside its bar's `[low, high]`; no fill better than SL/TP on a gap.
- No position entered on a date whose score used data after the prior close — assert the
  score's `asof` strictly precedes the entry bar.
- Converted positions never exceed available cash (proves the no-leverage assumption).
- Every screened pick is either entered or logged with a skip reason; counts reconcile.
- Sum of per-trade costs equals the equity-curve cost drag (the README records a bug where
  drag was reported against starting capital rather than the running book, overstating it 12×).
- Gate numbers recomputed on the dev window must land within a reasonable distance of the
  full-sample figures quoted here; a large divergence means the holdout split is wrong.

## README update

Add **Part 3 — Hybrid intraday-to-delivery (₹5,000)** after Part 2, matching the existing
voice: the measurement first, the verdict plainly, tables with t-stats, and what the
result does and does not establish. Update the `Layout` block and the `Running it` section.
The cost-model table gains a Hybrid column. If the hybrid arm is rejected and the delivery
arm passes, say so in those words in the opening summary — the README's credibility comes
from Part 1 being a documented rejection.

---

## Manual items — things I cannot settle from the repo

1. **Verify with Angel One whether MIS→CNC conversion reclassifies the buy leg's STT to
   delivery (0.1%) and stamp duty to 0.015%.** Worth ~11 bps on ₹5,000 and it is the only
   materially uncertain input in the whole cost model. Check a real contract note for a
   converted position, or ask support. Default until then: conservative (it does).
2. **Confirm Angel One's DP charge** — ₹20 + GST per scrip on sell is assumed from the
   existing model; some brokers bill it as ₹13.5 + ₹5.5. At ₹5,000 this single line is
   47 bps, so it is worth reading off a contract note rather than a rate card.
3. **Confirm the MIS→CNC conversion cutoff and any conversion fee** on Angel One's
   platform. 15:00 was chosen conservatively; the real deadline may be later.
4. **Confirm ₹5,000 is the real figure and whether it grows.** At ₹25,000 the hybrid cost
   falls 94.8 → 54.6 bps and at ₹50,000 to 45.2. Nothing else in this plan changes the
   economics as much as this one number.
5. **Decide on slippage for tiny orders.** The repo assumes 5 bps/leg and measured +0.8
   bps/leg net over 1,740 legs. A ₹5,000 order moves no Nifty 200 stock, so 1–2 bps is
   arguably right — but it barely matters here (94.8 vs 86.8 bps), so I will keep 5 and
   report the sensitivity rather than argue for a favourable assumption.
6. **`data/` needs no refresh for this work** — daily covers 2011-08-24 → 2026-08-21 and
   intraday 2024-08-22 → 2026-08-22, 0 NaNs, 75 bars/day 09:15–15:25, 15:00 bar present on
   every day. Extending the intraday history would need Angel One credentials in `.env`
   and a run of `data/fetch_universe.py` off the corporate network (`RUN_AT_HOME.md`).
   Two known quirks I will code around rather than ask you to fix: `PEL` has only 190 days
   of daily history, and one symbol carries a stray 2026-08-22 (Saturday) intraday session.
7. **`matplotlib` and `scipy` are not in `.venv`** — the CI workflow pip-installs them
   separately, so chart generation currently only works in Actions. I will add both to
   `requirements.txt` so `analysis.py` runs locally; say if you would rather keep charts CI-only.
