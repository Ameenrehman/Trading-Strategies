# Phase 1b — Delivery (CNC) Momentum

Goal: find a systematic, long-only equity strategy that beats simply buying and holding the index, after realistic Indian delivery costs. Runs entirely locally on historical daily data — no orders, no regulatory constraints.

**Status (2026-08-22): run on real data. All 6 pre-registered criteria pass. Not validated for capital — see §6.**

205 Nifty 200 symbols, 15.0 years of daily bars (2011-08-24 → 2026-08-21). 16/16 sanity checks pass.

| | CAGR | Vol | Sharpe | Max DD | Turnover/yr | Cost/yr |
|---|---:|---:|---:|---:|---:|---:|
| **Momentum** 12-1 top 20 +200DMA | **29.22%** | 19.7% | **1.42** | −37.4% | 516% | 0.94% |
| Equal-weight buy & hold | 17.04% | 16.3% | 1.07 | −37.8% | 8% | 0.03% |
| Random selection (mean, 20 seeds) | 15.38% | — | 0.95 | −37.1% | — | — |
| Bottom decile by momentum | 12.21% | — | 0.75 | −41.8% | — | — |

**+12.18%/yr after costs, 20/20 random seeds beaten, bottom decile symmetrically worse.** The mirror pattern is what distinguishes a real ranking effect from equity beta plus a trend filter.

**Criterion 5 (walk-forward): PASS** — 7 of 9 out-of-sample windows won, mean edge +17.07%/yr, t = 2.47, and still +12.26%/yr with the single best window removed.

**Criterion 6 (recent 5 years): PASS at +8.92%/yr.** An earlier run reported this as a +2.04%/yr FAIL. That was a defect in the backtester's windowing, not a property of the strategy — see §5.7.

---

## 1. Why this phase exists

Phase 1 (intraday) is finished and the answer was no. See [`phase-1-backtesting.md`](phase-1-backtesting.md) for the full record. The short version: twelve strategies, 50 stocks, two years of clean 5-minute data. The best variant produced a **genuine** directional edge — +11.26 bps gross, t = 4.00 over 702 trades, beating 20/20 randomized-direction control seeds — but the intraday cost hurdle is ~14 bps. Breakeven needed 0.49 bps/leg slippage, i.e. zero market impact. The kill criterion fired.

The binding constraint was diagnosed precisely: **the same-day exit**. Median daily range on Nifty large-caps is 142–192 bps, so every intraday round trip spends 8–10% of the entire day's available movement on costs.

Holding longer attacks that directly, because moves scale with roughly √time while cost is paid once per trade:

| Hold | Median move | Delivery cost as % of move |
|---:|---:|---:|
| 1 day | 82 bps | 47.4% |
| 5 days | 201 bps | 19.4% |
| 20 days | 418 bps | 11.1% |
| 42 days | 609 bps | 7.6% |
| 63 days | 764 bps | 6.1% |
| **~70 days** (30% monthly turnover) | **~800 bps** | **~6%** |

**But delivery is 2.1× more expensive than intraday**, so this is not free. Short swings of 2–5 days are the worst of both worlds — you pay the delivery penalty without the move size to justify it. The viable zone is multi-week holds, which means this is no longer trading but **systematic momentum investing**.

---

## 2. Cost model — delivery (CNC)

In `backtest/costs.py`, alongside the intraday model (which is kept for the historical record — do not delete it, and do not confuse the two).

| Component | Delivery (CNC) | Intraday (MIS) |
|---|---|---|
| Brokerage | `max(₹5, min(₹20, 0.1%))` per order | `min(₹20, 0.03%)` per order |
| **STT** | **0.1% on BOTH legs** | 0.025% sell only |
| Exchange txn (NSE) | 0.00297% both | 0.00297% both |
| SEBI turnover | 0.0001% both | 0.0001% both |
| Stamp duty | **0.015% buy only** | 0.003% buy only |
| GST | 18% on (brokerage + exchange + SEBI + DP) | 18% on (brokerage + exchange + SEBI) |
| **DP charges** | **₹20 per scrip on SELL** | none |

Round-trip cost, verified by `python backtest/costs.py`:

| Position | 5 bps/leg | 3 bps/leg | 2 bps/leg |
|---:|---:|---:|---:|
| ₹50,000 | 46.4 | 42.4 | 40.4 |
| ₹100,000 | **39.3** | 35.3 | 33.3 |
| ₹200,000 | 35.8 | 31.8 | 29.8 |
| ₹500,000 | 33.6 | 29.6 | 27.6 |

**STT alone is 20 bps — 50.9% of the total on a ₹1L position — and is purely proportional, so it never amortises.** That sets a hard floor around 26–33 bps regardless of size.

Two implementation details that matter:

- Costs are charged **per leg** via `delivery_one_way_cost(value, side)`. Charging a symmetric half round-trip would misplace STT (both legs), stamp duty (buy only) and DP charges (sell only) all at once.
- Slippage is **included** in the delivery model rather than handed to a `spread` parameter, because the portfolio backtester charges one cash cost per rebalance instead of adjusting individual fill prices.

### Annual drag, which is the number that makes this worth doing

| Portfolio | 30% monthly turnover | 50% monthly turnover |
|---:|---:|---:|
| ₹5,00,000 | 2.18%/yr | 3.63%/yr |
| ₹10,00,000 | 1.67%/yr | 2.78%/yr |
| ₹25,00,000 | 1.36%/yr | 2.27%/yr |

~1.4–2.8%/year against a momentum premium historically in the high single digits. Intraday, by contrast, had costs exceeding the entire edge.

**Minimum viable capital is around ₹5L.** Below that, the flat ₹20 brokerage and ₹20 DP charge per scrip push drag above 2%/yr and the strategy is structurally disadvantaged.

---

## 3. Strategy

`strategies/momentum_xs.py`. Signal generation only — broker-agnostic, same as the rest of `strategies/`.

- **Ranking:** 12-1 momentum — trailing 12-month return **skipping the most recent month**. The skip is not cosmetic; the recent month carries short-term reversal that contaminates the signal.
- **Trend filter:** hold only names above their 200-day moving average. This is what cuts momentum's crash drawdowns.
- **Selection:** top 20 that also pass the trend filter. If fewer than 20 qualify, hold fewer and sit partly in cash — backfilling with names that fail the filter would defeat the point of having one.
- **Weighting:** equal weight at entry, then left to drift.
- **Rebalance:** monthly, at month-end close.
- **Eligibility:** minimum median daily traded value over the trailing 3 months, computed **point-in-time** from data available at that date only.

### How positions are exited — there is no stop-loss or take-profit

This is the biggest conceptual departure from the intraday work, so it is worth stating plainly. **The rebalance is the exit.** Each month the universe is re-ranked and:

- **hold** — still in the top 20 *and* still above its 200-DMA
- **sell** — dropped out of the top 20, *or* fell below its 200-DMA
- **buy** — newly qualified on both counts

Holding period is therefore variable and endogenous. A stock that keeps trending is held indefinitely — winners running is where momentum's return actually comes from. A stock that rolls over is gone at the next rebalance, so the worst case is roughly one month of decay. At the ~30% monthly turnover the framework produces, the average hold is about **3.3 months**.

The 200-DMA filter is the systematic stop: portfolio-level and scheduled rather than an intraday trigger.

**Why no hard stop-loss:**

1. Momentum is a cross-sectional, statistical edge. Per-trade stops convert a diversified edge into path-dependent bets and truncate the fat right tail, which is the part you cannot afford to lose.
2. Turnover is the dominant cost lever (30% vs 50% monthly is 1.67% vs 2.78%/yr). Stops raise turnover.
3. A stop firing between rebalances re-introduces exactly the timing sensitivity the intraday work died on.

**The genuine risk this creates is gap risk between rebalances** — a name can fall sharply on news and be held to month-end. Rather than assume that away, three exit modifiers are implemented and **tested** rather than asserted, all defaulting to off:

- `disaster_stop_pct` — hard stop checked daily (e.g. 0.25 for −25% from entry)
- `trend_exit_daily` — check the 200-DMA daily instead of only at rebalance
- `exit_rank_buffer` — hold until a name drops out of the top (20 + buffer), which *reduces* turnover

`backtest/test_momentum.py` runs all three so the question is settled with numbers.

---

## 4. Engine — why a new backtester

`Backtesting.py` is single-instrument. Cross-sectional ranking across 200 names cannot be expressed in it, so none of the intraday tooling (`run_backtest.py`, `verify_fixes.py`, `test_gap_rvol.py`, `validate.py`) carries over.

`backtest/portfolio.py` is a small, explicit monthly-rebalance backtester in pandas. Deliberately **not vectorbt**: the entire point of this phase is a cost model we trust, and vectorbt was already deferred once in Phase 1 for unverified SL/TP/EOD behaviour. A ~250-line loop over ~180 rebalance dates is fast enough and auditable.

**Existing positions are left to drift by default** (`weight_band=0`). Forcing every holding back to equal weight each month generates large turnover for no expected return, and letting winners run is the behaviour momentum depends on. Set `weight_band=0.5` to rebalance only positions that have drifted more than 50% from target.

What it does *not* model, stated so it isn't discovered later: **dividends** (returns are price-only, which understates the strategy and the benchmark roughly equally, so comparisons stay fair), intraday fills (everything transacts at the rebalance close), and corporate actions beyond whatever the feed already adjusts.

### Verified before use

`backtest/test_portfolio_sanity.py` — 16 checks on synthetic data with known answers, because a portfolio backtester is easy to get subtly wrong in ways that flatter the result. Phase 1 shipped eight such defects before they were caught.

```
[PASS] zero-cost buy&hold matches manual calc          diff 0.0000%
[PASS] turnover == 0 when selection never changes      max after build 0.00e+00
[PASS] charged cost == delivery_one_way_cost per leg   err Rs.0.0000
[PASS] momentum ranks the strongest drifters top
[PASS] 12-1 momentum ignores the skipped recent month
[PASS] trend filter drops a name below its 200-DMA
[PASS] holds cash when nothing qualifies
[PASS] signal_fn never sees data beyond the rebalance date
[PASS] one-way legs sum to the round-trip cost         Rs.393.05 vs Rs.393.05
[PASS] cost drag independent of portfolio growth       reported 0.025%/yr vs expected 0.025%/yr
... 16/16
```

Three real defects were caught this way before any market data was involved: the backtester was force-rebalancing every holding to equal weight monthly (creating large artificial turnover), new entries could be sized beyond available cash, and `momentum_scores` mis-indexed at the exact history boundary (only daily rebalancing lands there, so monthly testing never hit it).

A fourth surfaced only once real data arrived, and is the reason for check 15. **Cost drag was computed as total rupees ÷ *initial* capital ÷ years.** Over 15 years the book compounded 42.8×, so the reported figure was inflated by roughly that multiple: it printed **12.19%/yr when the true drag was 0.94%/yr**. The equity curve was correct throughout — costs were always charged correctly against the running portfolio — but every published cost table was 12× too high, and it made daily rebalancing look unaffordable when it is not. Check 15 pins drag to the turnover and cost rate implied by the trade log itself, on a synthetic book that grows ~89,000×.

---

## 5. Validation

### The benchmark is the bar, not zero

A long-only equity strategy making money proves nothing — the market rises. The strategy must beat **equal-weight buy-and-hold of the same universe, after costs**.

Note this is a genuinely tough benchmark, and deliberately so: buy-and-hold with drifting weights lets winners compound into larger positions, which is *itself* momentum-like. It also pays almost no cost (buy once, hold). Beating it is the real test, and it is what a retail investor's actual alternative looks like.

### Controls — the test that decided Phase 1

The randomized-direction control was the single most valuable thing in the intraday work, so its analog is built in from the start (`backtest/test_momentum_controls.py`):

- **Control A — random selection.** Same universe, same eligibility and trend filter, same weighting, same costs, same dates. Only *which* 20 names is randomised. 20 seeds.
- **Control B — bottom decile.** Hold the worst names by rank. A real effect shows the mirror pattern seen in the gap test: top beats random, bottom is symmetrically worse.

The alternative explanation these kill: momentum "works" only because it holds whatever went up, in a market that rises. If random selection from the same eligible, in-trend pool does as well, the ranking adds nothing and the apparent edge is trend filter plus equity beta.

### Survivorship bias — the biggest threat

Applying **today's** Nifty 200 membership to years of history only tests companies that survived *and* made it into the index. Free data cannot fix this — delisted names aren't in the scrip master at all.

Mitigations actually implemented, not just disclaimed:

1. Eligibility filters are **point-in-time**, computed only from data available at each rebalance date.
2. Results are reported on **both** the full window and the recent 5 years, where index drift is smallest. A large gap between them is a survivorship-bias signature.
3. The outperformance bar is **3%/yr, not "positive"**, because the bias is plausibly worth ~2%/yr.

### 5.5 What the real data said

**The controls passed decisively.**

```
REAL (top 20 by momentum)     29.22%   Sharpe 1.42   maxDD -37.4%
BENCHMARK (equal-weight B&H)  17.04%   Sharpe 1.07   maxDD -37.8%
Control A random (mean of 20) 15.38%   Sharpe 0.95   maxDD -37.1%
Control B bottom decile       12.21%   Sharpe 0.75   maxDD -41.8%

Random seeds matching or beating the real strategy: 0/20
```

Momentum beat every random seed drawn from the same eligible, in-trend pool, and the bottom decile came in 3.17%/yr *below* random. Both directions matter: if the ranking were noise, top and bottom would straddle random symmetrically at zero. They don't — the ranking carries information.

**Criterion 6 passes at +8.92%/yr.**

Over the trailing 5 years momentum returns 25.59%/yr against the benchmark's 16.67%, with a higher Sharpe (1.17 vs 1.04) but a worse drawdown (−30.4% vs −22.9%).

An earlier run of this section reported +2.04%/yr and scored criterion 6 as a FAIL. That number was produced by a defect in the backtester's windowing, described in §5.7 — momentum was forced to sit in cash for the first ~14 months of the window while the benchmark was fully invested throughout. It is recorded here rather than quietly replaced, because the wrong number was circulated before it was caught.

The year-by-year table remains the more informative view:

| Period | Mean annual edge | Years won |
|---|---:|---:|
| 2012–2018 | +9.0%/yr | 4/8 |
| 2021–2026 | +16.8%/yr | 4/6 |

Survivorship bias inflates the **oldest** data most — today's index membership excludes the companies that failed along the way. An edge driven by that bias would be concentrated in 2012–2016. It is not; the recent years are stronger.

What the 5-year window actually catches is two things:

1. **Window placement.** It starts in August 2021 and so misses most of that year's +50% relative run while fully including 2025.
2. **A genuine recent drawdown.** 2025 was −8.9% relative and 2026 is flat. Momentum has underperformed for roughly 18 months.

Sustained relative drawdowns are momentum's documented failure mode, not evidence the backtest is broken. But criterion 6 was written down before any data was seen, and it failed. It is recorded as a failure, not reinterpreted into a pass — and it is exactly what walk-forward and the holdout exist to adjudicate.

### 5.6 Walk-forward — and what it says about the variant sweep

`backtest/walk_forward.py`, development period only (holdout sealed), nine non-overlapping 1-year out-of-sample windows.

**A. Stability of the pre-registered baseline, never re-fitted:**

| | |
|---|---|
| Windows won | **7 / 9** |
| Mean out-of-sample edge | **+17.07%/yr** |
| Median edge | +8.95%/yr |
| t-stat across windows | **2.47** |
| Worst window | −4.87%/yr (2015-08 → 2016-08) |
| Mean excluding the single best window | +12.26%/yr |

The single best window (2020-08 → 2021-08, the COVID recovery, +55.5%) does not carry the result — removing it leaves +12.26%/yr.

**B. Selection — the actual overfitting test.** 14 variants have been tried on this data. In each fold the best candidate by in-sample Sharpe was chosen and applied to the *next* unseen window:

| | |
|---|---|
| Selection beat the fixed baseline in | **3 / 9 windows** |
| Mean (selected − baseline) | **−3.41%/yr** |
| Distinct variants chosen across folds | 6 of 11 |

**Chasing the best in-sample variant lost to the pre-registered baseline**, and the choice was unstable — six different variants won across nine folds. That is what fitting noise looks like. The practical consequence: trade the baseline, not the sweep winner (`6-1 momentum` had the highest full-period CAGR at 30.19%, and it was selected in three folds where it then underperformed the baseline by 18.6, 19.2 and −13.8 points respectively).

This is the single most decision-relevant result in the phase, and it is a *negative* one.

### 5.7 A third backtester defect, found by walk-forward

The first walk-forward run returned 0.0% CAGR and a `nan` Sharpe in all nine windows — obviously wrong, and worth reporting because of what it exposed.

`run_portfolio`'s `start`/`end` parameters were slicing **`closes` itself**, not the trading calendar. A strategy needing 252 + 21 days of history, handed a 1-year window, therefore saw no history at all: it selected nothing, held cash, and returned exactly 0%.

That silently corrupted a published number. The §5.5 "recent 5 years" comparison passed `start=recent_start`, so momentum spent the first ~14 months of that window in cash while the benchmark — which needs no warm-up — was fully invested from day one. **The reported +2.04%/yr and its criterion-6 FAIL were an artifact of that handicap.** Corrected, the same window gives +8.92%/yr.

The fix makes `start`/`end` bound the trading window while leaving full history available to `signal_fn`. Sanity check 16 pins it: a strategy run on a window shorter than its own lookback must still trade.

Three of the four defects found in this phase were caught by known-answer tests; this one was caught because a validation script produced a result too clean to be real. Both routes matter.

### 5.8 Unadjusted corporate actions — a defect found in the data, not the code

Angel One serves **unadjusted** closes. A demerger or relisting therefore appears as a single-day step that no shareholder experienced. For momentum this is not cosmetic: the ranking is a trailing 12-month return, so one such step parks a phantom stock at the top or bottom of the ranking for **twelve consecutive rebalances**.

Scanning all 205 symbols at ≤ −50% / ≥ +100% in one day returned exactly three:

| Symbol | Date | Step | Cause |
|---|---|---:|---|
| ADANIENT | 2015-06-03 | −80.9% | demerger — holders received shares in the spun-out entities |
| PATANJALI | 2020-01-27 | +406.2% | Ruchi Soya relisting after a 75-day trading halt |
| YESBANK | 2020-03-06 | −56.1% | RBI moratorium — a *genuine* loss, truncated anyway |

`data/corporate_actions.py` truncates each symbol's history to begin after its last such event, so it behaves like a name that listed on that date. Truncation is preferred to dropping the symbol, which would remove a genuine constituent from 15 years of universe and create its own selection bias.

The detector cannot distinguish a real crash from a data artifact — that requires knowing the corporate event, which is precisely what free price data lacks. So the rule is applied uniformly and the affected symbols are reported, rather than hand-picking which to "fix". Hand-picking is where bias enters unnoticed. The cost of the false positive is one symbol's pre-2020 history; the cost of a false negative is a fabricated top-ranked stock held for a year.

**It was not harmless.** Uncorrected, the strategy bought PATANJALI at ₹457 on a manufactured signal and sold it at ₹201. Repairing the three symbols raised CAGR from 28.48% to 29.22% — the contamination was *costing* return, not creating it.

### 5.9 Monte Carlo permutation test

`backtest/test_permutation.py`, development period only.

The randomized controls in §5.5 test the *selection*: does the top decile beat a random draw from the same eligible pool? They cannot test whether momentum exists in the data at all, because both arms trade the same real price paths.

The permutation test shuffles the **order** of the daily cross-sectional return matrix, one common permutation applied to every symbol. Preserved: each symbol's return distribution, each day's cross-section (so market moves and correlations survive), the calendar, the universe, every listing date, the eligibility filter and the cost model. Destroyed: the temporal sequence, and nothing else. Strategy and benchmark are both re-run on each shuffled path; the statistic is the difference, because shuffling changes how the whole market compounds and an absolute CAGR from shuffled data is not comparable to the real one.

| | |
|---|---:|
| Real edge | **+15.92%/yr** |
| Null mean / std | +0.41% / 2.30 |
| Null 5th / 50th / 95th percentile | −3.44% / +0.29% / +4.33% |
| Null max over 400 runs | +7.85% |
| Runs matching or beating the real edge | **0 / 400** |
| z-score | **6.73** |
| Empirical p | 0.0025 (at the 1/(n+1) floor) |
| Normal-approx p | 8.5 × 10⁻¹² |

**Multiple testing.** 14 variants were swept, so the Bonferroni bar is 0.05/14 = 0.00357. Resolving that empirically needs at least 279 permutations, which is why 400 were run — 200 would have floored the empirical p-value at 0.005 and been unable to clear the bar regardless of the result. Both p-values pass.

The null centring on +0.41%/yr rather than exactly zero is the construction check: with the time-ordering destroyed, a trailing-return ranking has nothing left to rank on, and the edge collapses from +15.92 to noise.

**Establishes:** the temporal ordering of returns carries exploitable information; the edge is not an artifact of the universe, the calendar or the cost model. **Does not establish:** persistence, or freedom from survivorship bias — the null and the real run share the same hindsight-selected 205 symbols.

### Remaining checklist

- [x] Walk-forward across the available history, no parameter re-fitting between windows — §5.6
- [x] Keep a running count of every variant tested and apply the Bonferroni bar — 14 variants, bar 0.00357, cleared
- [x] Report turnover explicitly — it drives cost and is where an implementation error would hide
- [~] Out-of-sample holdout: **compromised**. It was meant to be touched exactly once at the end; the first real-data run had no holdout handling and spanned the whole history, so the trailing 24 months were observed. `split_holdout()` now enforces the boundary, and walk-forward and the permutation test respect it — but the honest remaining out-of-sample test is forward time, not a re-labelled slice of history.

---

## 6. Go / no-go — pre-registered before any real data was seen, now scored

| # | Criterion | Result | |
|---|---|---|---|
| 1 | Beats equal-weight buy-and-hold by ≥ 3%/yr CAGR after costs | +12.18%/yr | **PASS** |
| 2 | Higher Sharpe, max drawdown no worse | 1.42 vs 1.07; −37.4% vs −37.8% | **PASS** |
| 3 | Beats ≥ 19 of 20 random-selection seeds | 20/20 | **PASS** |
| 4 | Bottom-decile control clearly worse than the benchmark | 12.21% vs 17.04% | **PASS** |
| 5 | Survives walk-forward without re-fitting | 7/9 windows, +17.07%/yr, t=2.47 | **PASS** |
| 6 | Holds up in the recent-5-year subsample | +8.92%/yr | **PASS** |

**The call: the strategy passes every pre-registered test. It is still not cleared for capital.**

That is not hedging — the criteria were designed to be necessary, not sufficient. Three things stand between here and a funded account, and none of them is another backtest:

1. **The holdout is compromised.** It was meant to stay sealed until exactly one final test. The first real-data run had no holdout handling whatsoever and spanned 2011–2026, so the trailing 24 months were observed — in the headline, in the recent-5-year row, and in the year-by-year table. Nothing was *tuned* on them, which makes this weak contamination rather than fatal, but a holdout you have looked at is no longer a holdout. `split_holdout()` now enforces the boundary and walk-forward and the permutation test respect it. **The honest remaining out-of-sample test is forward time.**
2. **Slippage is assumed.** The entire cost model rests on 5 bps/leg, which is a guess. The current buy list includes names trading near ₹14, where real slippage could be several times that. Only live or paper fills settle it.
3. **Survivorship bias is untouchable from here.** Every window, permutation and control draws on the same 205 symbols selected by *today's* index membership. No amount of resampling fixes a universe defined with hindsight.

The kill criterion did not fire, and the evidence for a real ranking effect is now strong across four independent angles: randomized controls, bottom-decile mirror, walk-forward stability, and the permutation test. But the intraday phase looked convincing on 5 symbols and collapsed on 50 — the discipline that produced that outcome is the same discipline that says *paper trade this before funding it*.

**Kill criterion:** if the strategy cannot beat buy-and-hold by 3%/yr after costs, stop. Buying and holding an index fund is then the correct answer, and that is a legitimate and valuable result — the same discipline that ended the intraday phase cleanly instead of bleeding money into it.

---

## 7. Data

**Nifty 200, daily bars, targeting 15 years.** `data/nifty200.json` (207 symbols), fetched by `data/fetch_universe.py --interval ONE_DAY`.

Two uncertainties were designed around rather than assumed. Both resolved favourably:

- **Request size.** Angel One documents 100 days per request at 5-minute, and forum reports mention a ~500-row response cap. The fetcher starts at 550-day chunks for daily bars and **halves the span and retries** whenever a response looks truncated. No truncation was detected in the completed pull.
- **History depth.** Daily history was expected to start around 2016–2017. It came back at **median 15.0 years**, earliest 2011-08-24 — the full requested window. 34 of 205 symbols have under 10 years, all genuine later listings (ADANIGREEN 2018, IRCTC 2019, SBILIFE 2017). The test window did not have to shrink.

**What actually came back:** 205 of 207 symbols resolved; `GUJGASLTD` and `LTIM` failed on scrip-master naming. Both are real Nifty 200 members, so this is a lookup mismatch rather than a missing company, and 203/205 coverage changes no conclusion — but it should be fixed before the holdout is spent.

**Audit findings.** `suspect_gaps` (>25% single-day move) flagged 38 symbols. Nearly all are genuine market events: the March 2020 COVID crash, the 2017-10-25 PSU-bank recapitalisation announcement (BANKBARODA, BANKINDIA, CANBK, PNB, SBIN, UNIONBANK all +27–46% on the same day), YESBANK's 2020 collapse, CGPOWER's 2019 accounting fraud. Seven symbols carry exactly one bar with an inconsistent OHLC relationship — 1 in ~3,700, and momentum reads closes only. The three genuine data defects are handled in §5.6.

Cost: ~2,000 requests, ~15 minutes, ~15–20 MB total. Angel One is firewalled on the work network, so this runs on a personal machine — see [`../RUN_AT_HOME.md`](../RUN_AT_HOME.md).

**On daily bars an unadjusted split is a clean −50%/−80% step.** Momentum ranks on trailing returns, so one unadjusted corporate action would park a phantom stock at the top or bottom of the ranking every month for a year. The fetcher's audit flags single-day moves above 25%.

---

## 8. From backtest to actually trading it

`live/generate_orders.py` produces the monthly order list. It imports `select()` from `strategies/momentum_xs.py` — **the same function the backtest calls** — so there is no separate live implementation to drift out of sync with the tested one.

```
Month-end, after close   ->  python live/generate_orders.py
                         ->  prints/writes SELL and BUY lists with quantities
Next morning at the open ->  place those orders as CNC/delivery
Every other day          ->  nothing
```

Roughly 12 order-generation events a year. On any other day the script says so and exits — that is the design working, not a failure.

It also estimates the cost of the generated orders, and prints a reminder that `ref_price` is the rebalance close rather than a limit: the difference between it and the actual fill **is** the slippage the backtest assumes at 5 bps/leg. Recording fills is how that assumption gets checked against reality, which is the main open question the backtest cannot answer.

---

## 9. Tasks

**Done**
- [x] Delivery cost model, verified against current published rates
- [x] Portfolio backtester with per-leg cost accounting
- [x] 16/16 sanity checks on synthetic data with known answers
- [x] Cross-sectional momentum + trend filter
- [x] Random-selection and bottom-decile controls
- [x] Exit-rule variants (disaster stop, daily trend exit, rank buffer) so the stop-loss question is testable
- [x] Order generation sharing the backtest's signal code
- [x] Nifty 200 universe list and daily-capable fetcher

- [x] **Fetch the daily data** — 205 symbols, 15.0 years, `data/daily/`
- [x] Check the fetch report: history depth, unresolved symbols, suspect gaps
- [x] Detect and neutralise unadjusted corporate actions (`data/corporate_actions.py`)
- [x] `python backtest/test_momentum.py` — +12.18%/yr over benchmark after costs
- [x] `python backtest/test_momentum_controls.py` — 20/20 seeds beaten, mirror pattern intact
- [x] Score §6 explicitly in writing — 5 pass, 1 fail, not established

- [x] **Walk-forward**, no re-fitting between windows — criterion 5 PASS (7/9, +17.07%/yr, t=2.47)
- [x] **Selection walk-forward** — chasing the best in-sample variant loses to the baseline by 3.41%/yr
- [x] Fix `start`/`end` slicing price history instead of the trading window (§5.7); criterion 6 PASS at +8.92%/yr
- [x] `split_holdout()` — enforce the holdout boundary in code rather than by intention

**Next**
- [ ] **Paper trade forward.** This is now the only genuinely out-of-sample test available, and it also measures the slippage the cost model currently assumes.
- [ ] Resolve `GUJGASLTD` and `LTIM` in the scrip-master lookup
- [ ] Verify `nifty200.json` against the live NSE constituent list
- [ ] Decide what the compromised holdout is still worth, and whether to re-cut it

## Verification

- `python backtest/costs.py` — ₹1L delivery = 39.3 bps, STT is 50.9% of it
- `python backtest/test_portfolio_sanity.py` — 16/16
- `python data/corporate_actions.py` — lists the 3 repaired symbols and the thresholds
- `python backtest/test_momentum.py --data-dir <dir>` — runs against any dataset
- `python backtest/verify_fixes.py` — the intraday work still passes its invariants
