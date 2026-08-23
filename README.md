# Trading-Strategies

Systematic NSE equity strategies tested against a realistic Indian cost model — and measured honestly enough to tell a real edge from a bookkeeping illusion.

Three parts, in order:

1. **Intraday** — 12 strategies, tested, **rejected**. A genuine edge was found and shown to be smaller than its own trading costs.
2. **Delivery / CNC momentum** — the main result. Run on 15 years of real data: **+12.18%/yr over buy-and-hold after costs, all six pre-registered criteria passed.** Not yet traded, on paper or otherwise.
3. **Hybrid intraday-to-delivery on ₹5,000** — **rejected at the screener**, before any execution engine was written. The proposed ranking is significantly *anti*-predictive at a one-day horizon.

**Scope:** long-only NSE cash equity. No options, no derivatives, no small-caps.

---

## The core idea

Most retail backtests fail the same way: they report **total return**, size every trade at ~100% of equity, and conclude that costs killed an otherwise good strategy.

That hides the actual question. With full-equity sizing, total return is roughly the per-trade edge compounded over the trade count — so a strategy trading 400×/year looks catastrophic and one trading 70×/year looks promising, purely because it paid the toll fewer times. **You end up ranking strategies by how little they trade.**

This repo measures **gross edge → realised cost → net edge**, with t-stats, multiple-testing correction, and randomized controls. That change reversed most of the original conclusions.

---

# Part 1 — Intraday (complete, rejected)

11 strategies across 4 families, 5 large-caps, 2 years of 5-minute bars, zero-cost runs to isolate the raw signal:

| Strategy | Family | Trades | Gross bps/trade | t |
|---|---|---:|---:|---:|
| Gap + ORB continuation | selectivity | 343 | **+7.67** | 1.95 |
| Trend Gap + EMA trail | selectivity | 560 | **+7.27** | 2.59 |
| NR7 / Inside-Bar | selectivity | 458 | **+5.04** | 1.92 |
| Prev-day High/Low | selectivity | 1677 | **+3.58** | 2.35 |
| VWAP breakout | VWAP | 1954 | +0.75 | 0.48 |
| Supertrend | trend | 1691 | +0.52 | 0.32 |
| Naive ORB 30m | ORB | 1942 | -0.88 | -0.48 |
| EMA momentum | trend | 1328 | -2.68 | -1.55 |

The ordering isn't random: the top four all decide *which sessions to trade*. Every ORB, VWAP, trend and mean-reversion variant sits at or below zero. Naive ORB has **no edge at all** — its headline −56% two-year return is entirely toll.

The best variant (gap ≥1% + RVOL filter + ATR trailing stop) reached **+30.7 bps gross / +15.8 bps net** on 5 symbols and beat **20/20** randomized-direction control seeds, with the inverted variant symmetrically negative. That ruled out "it's just volatility capture."

**Then it was tested on 50 symbols and collapsed:**

| Group | Trades | Gross bps | Net bps |
|---|---:|---:|---:|
| Original 5 symbols | 94 | +30.66 | **+15.78** |
| The other 45 | 608 | +8.26 | **−6.47** (t = −2.15) |
| **All 50** | **702** | **+11.26** (t = 4.00) | **−3.49** |

The 5 development names were a favourable draw. On the 45 never used to build the strategy, net edge is significantly **negative**.

**Verdict: no go.** The edge is real (+11.26 bps, t = 4.00) and simply smaller than the ~14 bps it costs to trade. Breakeven needs 0.49 bps/leg slippage — effectively zero market impact. The pre-registered kill criterion fired and no live money was risked.

The binding constraint: **the same-day exit**. Median daily range is 142–192 bps, so each intraday round trip burns 8–10% of the entire day's available movement.

---

# Part 2 — Delivery / CNC momentum (current)

Holding longer attacks that constraint directly, because moves scale with roughly √time while cost is paid once:

| Hold | Median move | Delivery cost as % of move |
|---:|---:|---:|
| 1 day | 82 bps | 47.4% |
| 20 days | 418 bps | 11.1% |
| ~70 days | ~800 bps | **~6%** |

**But delivery costs 2.1× intraday**, because STT is 0.1% on *both* legs instead of 0.025% sell-only. Short 2–5 day swings are the worst of both worlds. The viable zone is multi-week holds — systematic momentum investing, not trading.

**Strategy:** 12-1 cross-sectional momentum (trailing 12-month return, skipping the most recent month to avoid short-term reversal), filtered to names above their 200-DMA, top 20 equal-weighted, monthly rebalance.

**Exits:** no stop-loss, no take-profit. The rebalance *is* the exit — a name is sold when it drops out of the top 20 or falls below its 200-DMA. Winners are allowed to run, which is where momentum's return comes from, and the 200-DMA filter is the systematic stop. Hard stops, daily trend exits and rank buffers are implemented as *testable options* rather than assumptions.

**Status:** run on real data — 205 Nifty 200 symbols, 15.0 years of daily bars (2011-08-24 → 2026-08-21). 16/16 sanity checks pass. **5 of 6 pre-registered criteria pass; criterion 6 fails.**

### Result, after delivery costs

| | CAGR | Vol | Sharpe | Max DD | Turnover/yr | Cost/yr |
|---|---:|---:|---:|---:|---:|---:|
| **Momentum** 12-1 top 20 +200DMA | **29.22%** | 19.7% | **1.42** | −37.4% | 516% | 0.94% |
| Equal-weight buy & hold | 17.04% | 16.3% | 1.07 | −37.8% | 8% | 0.03% |
| Random selection (mean of 20 seeds) | 15.38% | — | 0.95 | −37.1% | — | — |
| Bottom decile by momentum | 12.21% | — | 0.75 | −41.8% | — | — |

**+12.18%/yr over the benchmark, and the controls hold:** momentum beat **20 of 20** random-selection seeds, and the bottom decile is symmetrically worse than random. That mirror pattern is what separates a real ranking effect from equity beta plus a trend filter.

**Over the most recent 5 years the edge is +8.92%/yr** (25.59% vs 16.67%), with a higher Sharpe (1.17 vs 1.04) but a worse drawdown (−30.4% vs −22.9%).

> An earlier version of this README reported that window as +2.04%/yr and a criterion-6 failure. That was a bug, not a result: `run_portfolio`'s `start` parameter sliced the *price history* rather than the trading window, so momentum sat in cash for the first ~14 months of any short window while buy-and-hold was invested from day one. Fixed, and pinned by sanity check 16.

Year by year, the record is strong but not uniform:

| Period | Mean annual edge | Years won |
|---|---:|---:|
| 2012–2018 | +9.0%/yr | 4/8 |
| 2021–2026 | +16.8%/yr | 4/6 |

The edge is **not** concentrated in the early years, which is the opposite of what survivorship bias predicts — that bias inflates the oldest data most, since today's index membership excludes companies that failed along the way. But momentum has genuinely underperformed for the last ~18 months: 2025 was −8.9% relative and 2026 is flat. That is momentum's documented failure mode, and it is what a live deployment would currently be sitting through.

### Walk-forward (criterion 5)

Nine non-overlapping 1-year out-of-sample windows on the development period, holdout sealed:

| | |
|---|---|
| Windows won | **7 / 9** |
| Mean out-of-sample edge | **+17.07%/yr** |
| Median edge | +8.95%/yr |
| t-stat across windows | **2.47** |
| Worst window | −4.87%/yr |
| Mean excluding the single best window | +12.26%/yr |

**The more useful half of this test asks whether the 14-variant sweep found anything real.** In each fold the best candidate by in-sample Sharpe was selected and applied to the next unseen window:

| | |
|---|---|
| Selection beat the fixed baseline in | **3 / 9 windows** |
| Mean (selected − baseline) | **−3.41%/yr** |

Chasing the best in-sample variant **lost** to simply trading the configuration written down before any data was seen. The sweep was fitting noise. That is a genuinely useful negative result: it removes any temptation to trade the sweep winner, and it is why the baseline stays the baseline.

### Permutation test and multiple-testing correction

The random-selection control asks whether picking the *top 20* beats picking *20 at random*. It cannot tell you whether momentum exists in the data at all. The permutation test does.

Method: shuffle the **order** of the daily cross-sectional return matrix, using one common permutation for every symbol. That preserves each symbol's return distribution, each day's cross-sectional structure and correlations, the calendar, the universe and every listing date — and destroys exactly one thing, the temporal sequence. Strategy *and* benchmark are re-run on each shuffled path and the statistic is their difference.

| | |
|---|---:|
| Real edge (development period) | **+15.92%/yr** |
| Null mean / std | +0.41% / 2.30 |
| Null 5th / 50th / 95th percentile | −3.44% / +0.29% / +4.33% |
| Null maximum over 400 runs | +7.85% |
| Shuffled runs matching or beating the real edge | **0 / 400** |
| z-score | **6.73** |
| Empirical p | 0.0025 (at the 1/(n+1) floor) |
| Normal-approx p | 8.5 × 10⁻¹² |

With 14 variants swept, the Bonferroni bar is 0.05 / 14 = **0.00357**. The empirical p-value clears it on its own — which is why 400 permutations were run rather than 200, since 200 floors the empirical value at 0.005 and could not have resolved the bar.

The null centring near zero (+0.41%) is itself the check that the test is built correctly: destroy the time-ordering and the edge disappears.

**What this establishes:** the ordering of returns carries information a trailing-return ranking can exploit, and the edge is not an artifact of the universe, the cost model or the calendar. **What it does not:** that the edge persists, or that it survives survivorship bias — every permutation draws on the same 205 symbols chosen by today's index membership, so that bias sits in the null and the real run alike.

### Unadjusted corporate actions

Angel One serves unadjusted closes, so a demerger or relisting appears as a single-day step no shareholder experienced. Momentum ranks on trailing 12-month returns, so one such step parks a phantom stock at the top or bottom of the ranking for twelve consecutive rebalances.

Three symbols in 205 carry one, and `data/corporate_actions.py` truncates each to start after the event:

| Symbol | Date | Step | Cause |
|---|---|---:|---|
| ADANIENT | 2015-06-03 | −80.9% | demerger (Ports/Transmission/Power spun out) |
| PATANJALI | 2020-01-27 | +406.2% | Ruchi Soya relisting after a 75-day halt |
| YESBANK | 2020-03-06 | −56.1% | RBI moratorium — a *genuine* loss, truncated anyway |

The detector cannot distinguish a real crash from a data artifact, so the rule is applied uniformly rather than hand-picking which to fix — that choice is where bias enters unnoticed. Leaving these in cost 0.74%/yr of CAGR: the uncorrected run bought PATANJALI at ₹457 on a fabricated signal and sold it at ₹201.

### Rebalance frequency is not the same thing as turnover

Turnover is what costs money, and a rank buffer controls turnover far better than a slower calendar does:

| Schedule | Turnover/yr | Cost/yr | CAGR |
|---|---:|---:|---:|
| Weekly + rank buffer 10 | 492% | 0.89% | **29.72%** |
| Daily + rank buffer 20 | 497% | 0.90% | 29.54% |
| Monthly (baseline) | 516% | 0.94% | 29.22% |
| Daily + rank buffer 10 | 686% | 1.24% | 28.99% |
| Monthly + rank buffer 10 | 323% | 0.58% | 28.43% |
| Quarterly | 280% | 0.51% | 27.77% |
| Weekly, no buffer | 1,131% | 2.06% | 28.50% |
| **Daily, no buffer** | **2,624%** | **4.85%** | **24.39%** |

Naive daily rebalancing gives up ~4.8%/yr of CAGR churning names that oscillate across the top-20 boundary. With a buffer it costs *less* than the monthly baseline and exits faster. **A daily buy list is therefore viable — it just requires `--rank-buffer 20`.**

### Pre-registered go/no-go

Written down before any result was seen, and scored honestly:

| # | Criterion | Result | |
|---|---|---|---|
| 1 | Beats equal-weight buy-and-hold by ≥3%/yr CAGR after costs | +12.18%/yr | **PASS** |
| 2 | Higher Sharpe, max drawdown no worse | 1.42 vs 1.07; −37.4% vs −37.8% | **PASS** |
| 3 | Beats ≥19 of 20 random-selection seeds | 20/20 | **PASS** |
| — | *Permutation test (added, not pre-registered)* | 0/400, p < Bonferroni bar | **PASS** |
| 4 | Bottom-decile control clearly worse | 12.21% vs 15.38% random | **PASS** |
| 5 | Survives walk-forward without re-fitting | 7/9 windows, +17.07%/yr, t=2.47 | **PASS** |
| 6 | Holds up in the recent-5-year subsample | +8.92%/yr | **PASS** |

The 3% margin isn't arbitrary: applying today's index membership to years of history excludes companies that failed, and that bias is plausibly worth ~2%/yr.

**Kill criterion:** if it can't beat buy-and-hold by 3%/yr after costs, stop. An index fund is then the right answer.

**All six pre-registered criteria now pass.** That is a real result and it was not guaranteed — the intraday phase failed the equivalent test and was killed.

It is still not a licence to deploy capital, for three specific reasons:

1. **The holdout is compromised.** It was supposed to be sealed until the end. The first real-data run had no holdout handling at all and spanned 2011–2026, so the trailing 24 months were observed — including in the year-by-year table. Nothing was *tuned* on them, but a holdout you have looked at is no longer a holdout. `split_holdout()` now enforces the split, and walk-forward and the permutation test respect it. The honest remaining out-of-sample test is **forward** time, not a re-labelled slice of history.
2. **Slippage is assumed, not measured.** 5 bps/leg is a guess. Measuring it takes paper trading, not another backtest.
3. **Survivorship bias cannot be removed by any test here.** Every window, every permutation and every control draws from the same 205 symbols chosen by *today's* index membership.

---

# Part 3 — Hybrid intraday-to-delivery on ₹5,000 (rejected at the screener)

A proposal: screen daily after the close, buy the top 1–3 names MIS at the open with pre-computed SL/TP, convert whatever is in profit at 15:00 into CNC, and manage the delivery leg to +5% / −3%. Capital ₹5,000. The proposal itself said the screener was "the most critical step — the screener quality determines everything."

That is exactly right, and it is why no execution engine was written. **A screener built from daily bars can be scored on 15 years and 205 symbols without simulating a single intraday fill.** If the ranking carries no next-day information, no trade management can rescue it, and building the engine first is an expensive way to discover that. So the screener was gated first, against pre-registered criteria.

**It failed all three.**

| # | Criterion | Result | |
|---|---|---|---|
| G1 | Next-day open→close edge over the universe > 0, t > 2 | −6.2 bps, t = −2.55 | **FAIL** |
| G2 | Rank monotone: top-1 ≥ top-3 ≥ universe ≥ bottom-3 | bottom-3 (+9.8) beats top-3 (+8.6) and the universe (+7.8) | **FAIL** |
| G3 | Beats ≥ 19 of 20 random-selection seeds | 8/20 | **FAIL** |

Development window only, 24-month holdout sealed. G2 is the mirror test that validated the delivery momentum work in Part 2 — here it fires backwards.

Re-run on just the 50 symbols that have 5-minute data — the names the strategy could actually have traded — it fails harder: **G1 = −5.6 bps at t = −3.22, and G3 = 0 of 20 random seeds beaten.** Screening the full 205 while only 50 are tradeable would itself have been a selection bias, since only 15% of top-3 picks land in that 50; screening inside it removes the bias and the result gets worse, not better.

### Why the same-day leg cannot work

Decomposing the universe's own return answers it before any strategy is involved:

| Segment | bps/day | Hit rate | t |
|---|---:|---:|---:|
| Overnight (prev close → open) | **+18.4** | 75.3% | 17.7 |
| Intraday (open → close) | **−10.2** | 49.4% | −6.0 |
| Full day (close → close) | +7.8 | 59.0% | 4.2 |

Essentially all of the drift is delivered overnight and the continuous session is a net drag. **A design that buys at 09:15 and exits by 15:00 donates the first and pays the second**, before a single rupee of brokerage. That is the same binding constraint that killed Part 1, arriving from a different direction.

### Two of the six factors could not rank anything

The proposed score was six factors at 25/20/20/15/10/10. Two of them are arithmetically incapable of reordering a cross-section:

- **"Relative strength vs Nifty"** (20%) is `roc20(stock) − roc20(index)`. The index term is one number per date, identical for every symbol, and subtracting a per-date constant is rank-preserving. It was **rank-identical to plain 20-day ROC on 500 of 500 dates tested.** It survives in the built version only as a *regime filter*, comparing the index to its own moving average — which does do something.
- **"Above the 50-DMA"** (15%) was listed as both a hard filter and a weighted score. Once it is a filter, every surviving name scores identically.

The momentum leg was the deeper problem: a **20-day ROC with no skip** sits inside the short-term reversal window that `momentum_xs.py` deliberately skips a month to avoid. Scored as specified, the screener is significantly *anti*-predictive — **−11.1 bps vs the universe on open→close (t = −4.18)** and **−6.2 bps on close→close (t = −2.23)** — and it underperforms equal-weighting the universe at every holding period from 1 to 20 days.

Rebuilding it as a 60-day ROC skipping 5 days, with the two dead factors removed, improves it and is what G1–G3 above actually score. It still fails. Notably the corrected composite is **worse than its own best single factor** — momentum alone is +5.7 bps vs the universe at t = 2.03, the four-factor blend is +0.8 at t = 0.31 — which is what adding uninformative factors to a ranking does.

### The cost model was understated, and a real contract note fixed it

`brokerage_per_order()` charges `min(₹20, 0.03%)`. Angel One's actual 2026 intraday rate is the same `max(₹5, min(₹20, 0.1%))` schedule it uses for delivery. A real round trip supplied by the account holder:

| | Turnover | Charged | Model (legacy) |
|---|---:|---:|---:|
| Buy | ₹4,852 | ₹6.08 | — |
| Sell | ₹4,640 | ₹7.07 | — |
| **Round trip** | | **₹13.15 (27.1 bps)** | **₹5.01 (10.3 bps)** |

`intraday_leg_2026()` reproduces both legs **to the paisa**, and is asserted against them in `python backtest/costs.py`. Two details only matter at this size: STT and stamp duty are billed in whole rupees, and the ₹5 brokerage floor binds below ₹5,000 of turnover. The legacy functions are left untouched so Parts 1 and 2 still reproduce — the correction makes Part 1's rejection *wider*, not narrower.

**On ₹5,000, the DP charge dominates everything.** It is a flat ₹20 + GST = ₹23.60 per scrip per sell, confirmed against the account holder's own charges:

| Split | Each | MIS | Hybrid MIS→CNC | CNC | DP alone |
|---|---:|---:|---:|---:|---:|
| 1 position | ₹5,000 | 36.3 | **103.5** | 103.0 | 47.2 |
| 2 positions | ₹2,500 | 61.9 | 168.3 | 173.8 | 94.4 |
| 3 positions | ₹1,667 | 81.5 | **247.1** | 244.6 | 141.6 |

So the proposal's "+5% target, −3% stop, 1:1.67, needs a 38% win rate" is a statement about *prices*, not money. After costs it is **+3.96% / −4.03%, R:R 0.98, breakeven win rate 50.5%** on one position — and **71.5%** split three ways. Concentration is not a preference here; the flat DP charge makes splitting ₹5,000 structurally unaffordable.

Slippage is almost irrelevant at this size: moving it from 5 bps/leg to zero changes the hybrid round trip by 10 bps out of 104. **The cost is nearly all statutory and exactly known**, so "but slippage is only assumed" is not an available objection to this rejection.

### What survived, and what it isn't

One result passed. At a **40-day hold** the corrected screener beats the equal-weight universe by **+117 bps (t = 2.55, non-overlapping windows)**, and clears its own ₹5,000 round-trip cost at 20 and 40 days. Every shorter horizon is inside the noise:

| Hold | 1d | 3d | 5d | 10d | 20d | 40d |
|---|---:|---:|---:|---:|---:|---:|
| Edge vs universe (bps) | +0.8 | −5.0 | −8.9 | −0.8 | +7.9 | **+116.8** |
| t (non-overlapping) | 0.31 | −1.75 | −1.20 | −0.38 | 1.85 | **2.55** |

That is **not a reprieve for this strategy.** It is a different one: a multi-week position with no intraday leg, no MIS entry and no 15:00 conversion — none of which the gate tested. It is also close to what Part 2 already trades and has already validated, on a longer lookback and 20 names rather than 3. Treating it as a new finding would require benchmarking it head-to-head against that, on its own pre-registered criteria.

**Verdict: rejected at the screener.** No execution engine was built, because there is no point executing a selection that loses to picking at random.

**What this establishes:** that the proposed ranking is anti-predictive at a one-day horizon, that two of its six factors could not have contributed, and that ₹5,000 of capital faces a 104 bps hybrid round trip which a +5% target cannot comfortably clear. **What it does not:** that trade management is irrelevant. SL/TP truncation and the conversion rule change the *distribution* of outcomes, and daily bars cannot see that. The claim here is narrower — that the selection those rules would act on does not beat random, which makes the question moot rather than answered.

---

## Cost model

`backtest/costs.py`. All three models are kept side by side — conflating them is an easy way to build a strategy that looks profitable and isn't.

| Component | Delivery (CNC) | Intraday (MIS) | Hybrid (MIS buy → CNC sell) |
|---|---|---|---|
| Brokerage | `max(₹5, min(₹20, 0.1%))` per order | `min(₹20, 0.03%)` per order — **stale, see below** | `max(₹5, min(₹20, 0.1%))` both legs |
| **STT** | **0.1% BOTH legs** | 0.025% sell only | 0.1% sell, and buy if conversion reclassifies it |
| Exchange txn | 0.00297% both | 0.00297% both | 0.00297% both |
| SEBI | 0.0001% both | 0.0001% both | 0.0001% both |
| Stamp duty | 0.015% buy only | 0.003% buy only | 0.015% buy only |
| GST | 18% on (brokerage + exchange + SEBI + DP) | 18% on (brokerage + exchange + SEBI) | 18% on (brokerage + exchange + SEBI + DP) |
| **DP charges** | **₹20 per scrip on sell** | none | **₹20 per scrip on sell** |

Round-trip on ₹1,00,000 at 5 bps/leg slippage: **intraday 18.3 bps, delivery 39.3 bps.** STT alone is 20 bps of the delivery figure — 50.9% — and being purely proportional it never amortises with size.

**The hurdle is size-dependent.** Below ~₹5L of capital, fixed ₹20 brokerage and ₹20 DP per scrip push annual drag above 2%. At ₹5,000 it stops being a drag and becomes the strategy: a hybrid round trip costs **104 bps**, of which **47 bps is the DP charge alone**.

**The intraday brokerage rate above is out of date.** Angel One now charges the same `max(₹5, min(₹20, 0.1%))` for MIS as for CNC, which a real contract note (`₹4,852` buy → `₹6.08`, `₹4,640` sell → `₹7.07`) pins exactly. `intraday_leg_2026()` reproduces it to the paisa and is asserted against it; the legacy `round_trip_cost()` is deliberately left alone so Parts 1 and 2 still reproduce. Part 1's rejection was measured against the *understated* figure, so correcting it widens the rejection rather than threatening it.

---

## Layout

```
strategies/
  momentum_xs.py         # cross-sectional momentum + trend filter (current)
  hybrid_momentum.py     # hybrid intraday-to-delivery screener (rejected)
  session.py             # session structure, day-aware ATR, risk sizing (intraday)
  orb_strategy.py        # opening range breakout (rejected)
  gap_rvol_strategy.py   # gap + RVOL momentum (rejected)
backtest/
  costs.py               # intraday, delivery AND hybrid cost models
  hybrid_momentum/
    test_screener_gate.py    # the Part 3 gate — screener quality before any engine
  walk_forward.py        # criterion 5 + the variant-selection overfitting test
  test_permutation.py    # Monte Carlo permutation + Bonferroni
  portfolio.py           # rebalancing portfolio backtester
  test_portfolio_sanity.py   # 16 known-answer checks — run this first
  test_momentum.py           # momentum vs benchmark, variants, year-by-year
  test_momentum_controls.py  # random-selection and bottom-decile controls
  verify_fixes.py            # intraday invariant checks
  test_gap_rvol.py / test_gap_controls.py   # intraday (rejected)
live/
  generate_orders.py     # the actual buy/sell list, sharing the backtest's signal code
  portfolio_state.py     # the ONE definition of positions.json (see its docstring)
  paper_broker.py        # simulated fills against live opening quotes
  track_performance.py   # mark-to-market NAV vs buy-and-hold, plus a cost audit
  dashboard.py           # renders the book as a self-contained local HTML page
  test_paper_broker.py   # unit tests for paper execution invariants
  positions.json         # paper portfolio state (committed during Phase 2)
  paper_ledger.csv       # append-only fill log (committed during Phase 2)
data/
  fetch_universe.py      # chunked fetcher (5-min and daily) with integrity audit
  corporate_actions.py   # detects and neutralises unadjusted splits/demergers
  nifty200.json          # delivery universe
  daily/                 # 205 symbols x 15 years of daily bars (delivery)
  intraday_5min/         # 50 symbols x 2 years of 5-minute bars (intraday, rejected)
Learning-T/              # planning docs, methodology, full findings
```

## Running it

Requires **Python 3.13**. The virtualenv is deliberately not committed — it hardcodes absolute paths to the machine that built it.

```bash
git clone https://github.com/Ameenrehman/Trading-Strategies.git
cd Trading-Strategies

python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # macOS / Linux

pip install -r requirements.txt
```

Intraday results reproduce immediately — the 5-minute dataset is committed, no credentials needed:

```bash
python backtest/costs.py               # cost tables, both products
python backtest/verify_fixes.py        # intraday invariant checks
python backtest/test_gap_rvol.py       # the gap sweep
python backtest/test_gap_controls.py   # the control that killed it
```

The delivery/momentum results reproduce too — `data/daily/` is committed:

```bash
python backtest/test_portfolio_sanity.py    # 16/16 before trusting anything
python data/corporate_actions.py            # what gets repaired, and why
python backtest/test_momentum.py            # the main result
python backtest/test_momentum_controls.py   # the controls
python backtest/walk_forward.py             # criterion 5 + the anti-overfitting test
python backtest/test_permutation.py         # permutation test + Bonferroni
```

Part 3 reproduces from the same committed daily data:

```bash
python backtest/costs.py                                # includes the contract-note check
python backtest/hybrid_momentum/test_screener_gate.py   # the gate, and why it failed
python backtest/hybrid_momentum/test_screener_gate.py --universe intraday50
```

The gate seals the 24-month holdout by default; `--full-sample` includes it and
says so in the report header. It writes `gate_report.txt` plus the underlying
CSVs to `backtest/results/hybrid_momentum/`.

### Phase 2: Forward Paper Trading & Slippage Measurement

```bash
# 1. Verify paper broker execution invariants (unit tests):
python live/test_paper_broker.py

# 2. After 15:30 IST market close on rebalance dates (generate buy/sell list):
python live/generate_orders.py

# 3. Next morning at 09:15–09:30 IST market open (simulated fill & slippage capture):
python live/paper_broker.py               # fetches live opening quotes from SmartAPI
python live/paper_broker.py --mock        # offline / testing mode

# 4. Audit portfolio NAV, unrealized P&L, and slippage vs backtest assumptions:
python live/track_performance.py

# 5. Same thing as a page you can actually look at (writes live/dashboard.html):
python live/dashboard.py --open
```

Step 3 must run on a **later** day than step 2. The signal comes from the close
of day T, so filling at day T's own open buys six hours before the signal
existed — a look-ahead that reports favourable slippage and reads as free
money. `paper_broker.py` refuses to do it.

**What Phase 2 can and cannot establish.** It was scoped to measure slippage.
It cannot: the close-to-open gap has a standard deviation of ~112 bps per leg,
so a year of paper trading (~240 legs) pins the mean only to ±7 bps — it cannot
tell 5 bps from 0 from 15. `backtest/test_execution_gap.py` measures the same
quantity over 1,740 historical legs instead:

| | bps/leg |
|---|---:|
| Buy legs, raw | +30.2 |
| Sell legs, raw | −29.3 |
| **Net across both legs** | **+0.8** |
| Universe-wide overnight drift | +24.9 |
| **Momentum-specific excess** | **+4.5** (t = 1.44, not significant) |

Buys gap up, but so does the whole market, and the simultaneous sells recover
it. The 5 bps/leg assumption is **conservative**. What remains unmeasured is
market impact — the difference between the printed open and *your* fill — and
that genuinely does need live orders.

So paper trading is worth running for what it can show: that the pipeline works
end to end, and a forward out-of-sample record, which is the only clean one left
after the 24-month holdout was observed.

Refreshing the data needs Angel One credentials in `.env` (see `.env.example`):

```bash
python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15
```

Dependency versions are pinned — `pandas` 3.x and `numpy` 2.x both carry behaviour changes that move the numbers.

---

## Methodology notes

Things this repo tries to do properly, mostly because earlier versions got them wrong:

- **Measure gross edge, realised cost and net edge separately.** Total return conflates edge with trade frequency.
- **Fixed-fractional risk sizing**, not ~100% of equity per trade.
- **Randomized controls.** The intraday phase was decided by a randomized-direction test; the momentum phase has random-selection and bottom-decile controls built in from the start.
- **Multiple-testing correction.** Every variant tested raises the bar; the count is tracked and reported.
- **Point-in-time filters.** Eligibility is computed only from data available at each rebalance date.
- **Known-answer tests.** The portfolio backtester is verified against synthetic data where the correct result is known by construction — that caught three real defects before any market data was involved, and a fourth (cost drag reported against starting capital rather than the running book, overstating it 12×) once real data arrived.
- **Corporate-action audit before backtesting.** One unadjusted split fabricates an enormous fake signal, especially for momentum, which ranks on trailing returns.
- **Pre-registered kill criteria**, written before seeing results, and actually honoured.

## Caveats

Research code, not trading advice. Nothing here has been paper-traded or traded live, and no strategy has passed validation. The momentum work carries **survivorship bias** that free data cannot fully remove — today's index membership applied to historical data excludes companies that failed, which inflates backtested momentum returns. The year-by-year split argues the edge is not merely that bias, but does not eliminate it. Returns are price-only (no dividends), which understates strategy and benchmark roughly equally.

The Part 3 gate is a screening result, not an execution result. It establishes that the proposed ranking loses to random selection at a one-day horizon; it does **not** establish that stop-loss placement and the MIS→CNC conversion are worthless in general, because daily bars cannot see intraday path dependence. The claim is that the selection those rules would act on does not beat random, which makes the question moot rather than answered.

Momentum has underperformed the benchmark for roughly the last 18 months (2025: −8.9% relative). Sustained relative drawdowns are momentum's documented failure mode, not evidence the backtest is broken — but they are also exactly what a live deployment would have to sit through.

Backtested edges routinely fail in live execution: slippage on a momentum entry is plausibly worse than the 5 bps/leg assumed here, and measuring it for real is an open task.

Historical data under `data/` was retrieved via Angel One SmartAPI and is included for reproducibility. It is **unadjusted** for corporate actions; see `data/corporate_actions.py` for how that is handled and why it matters more for momentum than for most strategies.
