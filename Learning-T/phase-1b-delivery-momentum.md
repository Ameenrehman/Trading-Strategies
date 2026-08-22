# Phase 1b — Delivery (CNC) Momentum

Goal: find a systematic, long-only equity strategy that beats simply buying and holding the index, after realistic Indian delivery costs. Runs entirely locally on historical daily data — no orders, no regulatory constraints.

**Status (2026-08-22): built and validated on synthetic data; waiting on the real daily data pull.** Cost model, portfolio backtester, strategy and controls are written and passing 12/12 sanity checks. Nothing has been tested on real market data yet.

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

`backtest/test_portfolio_sanity.py` — 12 checks on synthetic data with known answers, because a portfolio backtester is easy to get subtly wrong in ways that flatter the result. Phase 1 shipped eight such defects before they were caught.

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
... 12/12
```

Two real defects were caught this way before any market data was involved: the backtester was force-rebalancing every holding to equal weight monthly (creating large artificial turnover), and new entries could be sized beyond available cash.

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

### Remaining checklist

- [ ] Walk-forward across the available history, no parameter re-fitting between windows
- [ ] Out-of-sample holdout: most recent 24 months, touched **exactly once**, at the end
- [ ] Keep a running count of every variant tested and apply the Bonferroni bar
- [ ] Report turnover explicitly — it drives cost and is where an implementation error would hide

---

## 6. Go / no-go — pre-registered before any real data is seen

1. Beats equal-weight buy-and-hold by **≥ 3%/yr CAGR after costs**
2. Higher Sharpe than the benchmark, and **max drawdown no worse**
3. Beats **≥ 19 of 20** random-selection seeds
4. Bottom-decile control clearly worse than the benchmark
5. Survives walk-forward without re-fitting
6. Holds up in the recent-5-year subsample, not just the full window

**Kill criterion:** if the strategy cannot beat buy-and-hold by 3%/yr after costs, stop. Buying and holding an index fund is then the correct answer, and that is a legitimate and valuable result — the same discipline that ended the intraday phase cleanly instead of bleeding money into it.

---

## 7. Data

**Nifty 200, daily bars, targeting 15 years.** `data/nifty200.json` (207 symbols), fetched by `data/fetch_universe.py --interval ONE_DAY`.

Two uncertainties designed around rather than assumed:

- **Request size.** Angel One documents 100 days per request at 5-minute, but forum reports also mention a ~500-row response cap. The fetcher starts at 550-day chunks for daily bars and **halves the span and retries** whenever a response looks truncated, because silent truncation would quietly put holes in the history.
- **History depth.** Angel One's daily history reportedly starts around 2016–2017 for many instruments. The fetcher attempts 15 years, accepts what comes back, and **reports actual per-symbol coverage**. If the median start is 2017, the test window shrinks and we say so rather than pretending the depth is there.

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
- [x] 12/12 sanity checks on synthetic data with known answers
- [x] Cross-sectional momentum + trend filter
- [x] Random-selection and bottom-decile controls
- [x] Exit-rule variants (disaster stop, daily trend exit, rank buffer) so the stop-loss question is testable
- [x] Order generation sharing the backtest's signal code
- [x] Nifty 200 universe list and daily-capable fetcher

**Next**
- [ ] **Fetch the daily data** (`RUN_AT_HOME.md`) — blocked on the corporate firewall
- [ ] Verify `nifty200.json` against the live NSE constituent list
- [ ] Check the fetch report: history depth, unresolved symbols, suspect gaps
- [ ] `python backtest/test_momentum.py` — the main result
- [ ] `python backtest/test_momentum_controls.py` — does the ranking carry information
- [ ] Walk-forward and Monte Carlo permutation
- [ ] Touch the 24-month holdout exactly once, at the end
- [ ] Make the §6 call explicitly, in writing

## Verification

- `python backtest/costs.py` — ₹1L delivery = 39.3 bps, STT is 50.9% of it
- `python backtest/test_portfolio_sanity.py` — 12/12
- `python backtest/test_momentum.py --data-dir <dir>` — runs against any dataset
- `python backtest/verify_fixes.py` — the intraday work still passes its invariants
