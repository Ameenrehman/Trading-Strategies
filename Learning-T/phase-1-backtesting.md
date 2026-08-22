# Phase 1 — Backtesting

Goal: prove a strategy has a real, non-curve-fit, post-cost edge on historical NSE data before risking any real-time attention or money on it. Runs entirely locally, no regulatory constraints (read-only historical data, no orders).

Strategy is the main deliverable of this whole project — this phase is allowed to take real time. Don't lock in the first idea that backtests positive; the validation checklist below exists specifically so you don't fool yourself.

**Status (2026-08-22): PHASE 1 COMPLETE — the kill criterion in §9 has fired. No strategy tested clears its costs. Recommendation: stop this direction.**

Round 1 tested 11 strategies across 4 families and found no post-cost edge. Round 2 fixed the implementation defects, built the Dynamic Gap + RVOL Momentum strategy, and showed **+30.7 bps gross / +15.8 bps net** on 5 symbols — passing a randomized-direction control decisively. Round 3 ran that same strategy on the full **50-symbol Nifty 50 universe**, and the result collapsed: **+11.3 bps gross, −3.5 bps net**. All 10 variants are net negative.

The 5-symbol result was a favourable draw, and the widened universe shows it plainly: the original 5 names give +30.7 bps gross, the other 45 give +8.3 bps and **−6.5 bps net (t = −2.15, significantly negative)**.

**What is actually true:** there IS a real directional edge — +11.26 bps gross with t = 4.00 over 702 trades is statistically solid, and the randomized-direction control confirmed it is not a volatility artifact. **It is simply smaller than the cost of trading it.** Breakeven would need slippage of **0.49 bps per leg** — effectively zero market impact. Even at an unrealistically generous 1 bps/leg, the strategy nets about **₹3,000/year** on ₹1 lakh positions. That is not a business.

---

## 1. How to read results here — the metric that matters

`backoff_handoff.md` reports total 2-year return per strategy (-56.3%, -53.5%, -8.5% …). **Total return is the wrong yardstick.** Round 1 used ~100% of equity per trade, so total return ≈ per-trade edge compounded over the trade count. With no real edge, a strategy that trades 400×/yr looks catastrophic and one that trades 70×/yr looks "promising" — purely because it paid the toll fewer times. Ranking by return ranks by *how little the strategy trades*.

**Use gross bps/trade, the realised cost, and net bps/trade — with a t-stat.** Re-running the round-1 candidates at zero cost isolates the raw signal. Pooled across 5 stocks, 2 years:

| # | Strategy | Family | Trades | **Gross bps/trade** | t-stat | Net @ 20.6 bps |
|---:|---|---|---:|---:|---:|---:|
| 1 | C: Gap + ORB continuation (≥0.5% gap) | selectivity | 343 | **+7.67** | 1.95 | -12.94 |
| 2 | Trend Gap + 20 EMA trailing exit | selectivity | 560 | **+7.27** | 2.59 | -13.34 |
| 3 | NR7 / Inside-Bar compression | selectivity | 458 | **+5.04** | 1.92 | -15.57 |
| 4 | Prev-day High/Low breakout | selectivity | 1677 | **+3.58** | 2.35 | -17.03 |
| 5 | B: VWAP breakout | VWAP | 1954 | +0.75 | 0.48 | -19.86 |
| 6 | Supertrend intraday | trend | 1691 | +0.52 | 0.32 | -20.09 |
| 7 | Trend + Vol filtered ORB | ORB | 913 | -0.14 | -0.06 | -20.75 |
| 8 | Gap fade (fill) | mean-rev | 346 | -0.17 | -0.05 | -20.78 |
| 9 | A: Naive ORB 30m | ORB | 1942 | -0.88 | -0.48 | -21.49 |
| 10 | VWAP pullback (mean reversion) | VWAP | 2114 | -2.05 | -1.60 | -22.66 |
| 11 | EMA momentum | trend | 1328 | -2.68 | -1.55 | -23.30 |

**Eleven strategies across four families.** The ordering is not random: the top four are all *selectivity* strategies — they choose which sessions to trade rather than trading every morning. Every ORB, VWAP, trend-following and mean-reversion variant sits at or below zero. That clustering is the actual finding of round 1, and it is what round 2 pursued.

Trade counts reproduce the handoff's runs (naive ORB 388/stock vs its "~400", Gap-ORB 68.6 vs "~69"), so this is the same experiment measured differently.

**Conclusions that still stand:**

1. **Candidate A (naive ORB) has no edge at all** — not "an edge destroyed by costs". Gross -0.88 bps, t = -0.48 over 1,942 trades. The entire -56% is toll.
2. **Nothing in round 1 survives multiple-testing correction.** Bonferroni over 11 tests needs |t| > 2.87; the best was 2.59.
3. **The gap/compression family was the only cluster leaning positive** — which is what round 2 pursued.

**Two claims from the handoff to drop:**

- *"Filtering for >0.5% gaps eliminated ~85% of low-volatility chop sessions."* Measured: a >0.5% gap happens on 26–48% of days (SBIN 26.4%, RELIANCE 29.5%, TCS 33.5%, HDFCBANK 40.2%, INFY 48.4%). The filter removes 52–74%, not 85%.
- *"TCS was profitable (+1.62%)."* Selection bias across 40 backtests, not a finding.

---

## 2. Implementation defects — all fixed and verified

Round 1's numbers came from code with eight defects. All are now fixed in `strategies/orb_strategy.py` and the shared helpers in `strategies/session.py`.

| # | Defect | Fix | Verified |
|---|---|---|---|
| 1 | No position sizing — `buy()` omitted `size`, so ~100% of equity went into every trade (median notional ₹100,421 on ₹100k cash) | Fixed-fractional risk sizing via `risk_based_size()` | median risk/trade **0.98%** of equity |
| 2 | Cost computed for a flat ₹50k position while positions were ~₹100k | `angel_intraday_commission()` — a per-order callable passed to Backtesting.py, exact at any size | reproduces the old model to the paisa at every size |
| 3 | Dead stop-loss branch: `min(range_low, price - 0.5*range)` could never bind, so realised RR was **1.87**, not 2.0 | Target sized off the true entry-to-stop distance | realised RR **2.000** |
| 4 | `_traded_today` set before the order sanity check, burning the session on a rejected order | Flag follows actual fills | one entry per session, 0 violations |
| 5 | ATR spanned day boundaries — the overnight gap counted as intraday range on the 09:15 bar | `day_aware_atr()` | first bar of session uses high−low |
| 6 | Positions leaked overnight when the feed ended at 15:10 — **4 confirmed** (e.g. HDFCBANK 2026-08-19 10:20 → 08-20 09:15, -₹1,098) | Exit fires on `eod_exit_time` **or** the last bar of the session | **0 overnight positions** |
| 7 | Opening range keyed to bar *count*, assuming bar 1 = 09:15 | Keyed to timestamps via `session_arrays()` | — |
| 8 | Entry filled at the close of the breakout bar, inflating stop distance | Resting stop orders at the range level | — |

**Effect of the fixes on ORB (`backtest/verify_fixes.py`):**

| | Trades | Gross bps/trade | t |
|---|---:|---:|---:|
| Before fixes | 1,947 | -0.82 | -0.45 |
| After fixes | 2,126 | **+0.44** | 0.26 |

**+1.26 bps.** As expected: the defects were worth a couple of bps, and ORB is still dead. The point of fixing them was to make round 2 trustworthy, not to rescue ORB.

**Also correct, and worth keeping:** the documented Backtesting.py end-of-day gotcha is handled properly by `trade_on_close=True` — `position.close()` fills on the 15:15 bar itself, not the next one.

---

## 3. Data quality — audited, clean

- 36,942 rows × 5 symbols, 493 trading days, 2024-08-22 → 2026-08-21. **No duplicate timestamps, no OHLC violations, no zero-volume bars.**
- **No corporate-action artifacts.** Largest overnight gaps are 5–8.5% and appear across multiple names on the same date (2026-02-03 ≈ +6% on all five; 2025-04-07 ≈ -6% on three) — real market events, not unadjusted splits. Angel One's feed appears already adjusted.
- All 493 sessions start at 09:15 with a complete opening-range window.
- **One artifact:** the last 15 trading days (2026-08-03 → 08-21) are truncated to 72–74 bars, some ending 15:10. This caused defect #6. Re-fetch or exclude.
- Median daily range: HDFCBANK 142 bps, RELIANCE 155, SBIN 164, TCS 171, INFY 192.

This audit is now automated in `data/fetch_universe.py --audit-only` and runs on every newly fetched symbol.

---

## 4. Round 2 result — Dynamic Gap + RVOL Momentum

`strategies/gap_rvol_strategy.py`, driven by `backtest/test_gap_rvol.py`. Only trade sessions that gapped, enter in the gap direction at the opening-range extreme, hold with an ATR chandelier trailing stop, size by fixed-fractional risk.

Pooled across 5 stocks, 2 years. `cost` is the **realised** cost at the sizes actually traded, not the flat ₹50k assumption:

| Variant | Trades | /stock/yr | Gross bps | gross t | Cost bps | **Net bps** | net t |
|---|---:|---:|---:|---:|---:|---:|---:|
| trail 2.0 ATR, gap ≥0.3% | 690 | 69.0 | 6.87 | 3.22 | 13.12 | -6.25 | -2.93 |
| trail 2.0 ATR, gap ≥0.5% | 422 | 42.2 | 9.42 | 3.25 | 13.44 | -4.01 | -1.39 |
| trail 2.0 ATR, gap ≥0.75% | 234 | 23.4 | 16.50 | 3.76 | 14.05 | +2.45 | 0.56 |
| trail 2.0 ATR, gap ≥1.0% | 161 | 16.1 | 18.10 | 3.23 | 14.34 | +3.76 | 0.67 |
| trail 2.0 ATR, gap ≥1.5% | 64 | 6.4 | 27.87 | 2.93 | 14.48 | +13.39 | 1.41 |
| fixed 2:1 target, gap ≥0.5% | 422 | 42.2 | 11.50 | 2.47 | 13.34 | -1.84 | -0.40 |
| fixed 2:1 target, gap ≥1.0% | 161 | 16.1 | 22.05 | 2.50 | 14.26 | +7.79 | 0.88 |
| **trail 2.0 ATR, gap ≥1.0%, RVOL ≥1.5** | **94** | **9.4** | **30.66** | **3.93** | **14.88** | **+15.78** | **2.02** |
| trail 2.0 ATR, gap ≥1.0%, trend filter | 161 | 16.1 | 17.91 | 3.19 | 14.35 | +3.57 | 0.64 |
| trail 3.0 ATR, gap ≥1.0% | 161 | 16.1 | 21.34 | 3.23 | 14.33 | +7.02 | 1.07 |

**What holds up:**

- **The monotonic gap-size relationship survived the rewrite and strengthened.** Gross edge rises 6.9 → 9.4 → 16.5 → 18.1 → 27.9 bps as the threshold goes 0.3% → 1.5%. Still monotonic, and the gross t-stats are now 2.9–3.9 (round 1 was 1.5–2.8) because risk-based sizing cut the variance.
- **Trailing exits beat fixed targets at low thresholds** but the fixed 2:1 wins at 1.0%, so the exit choice is not settled.
- **The RVOL filter is the single biggest contributor** — adding RVOL ≥1.5 to the 1.0% gap threshold lifts gross from 18.1 to 30.7 bps.

**What does not yet hold up:**

- **94 trades.** That is 9.4 per stock per year, far below the 200 the checklist demands.
- **Net t = 2.02, against a Bonferroni threshold of 2.81** for the 10 variants tested in this run. The gross t-stats clear it comfortably; the net ones do not, because subtracting ~15 bps of cost shifts the mean without shrinking the variance.
- **Best-of-10, chosen in-sample.** The out-of-sample holdout has still not been touched.

---

## 4b. Round 3 — the 50-symbol universe (the decisive test)

Same strategy, same code, same parameters. Only the universe changed: 5 symbols → 50, 702 qualifying trades instead of 94.

| Variant | 5 symbols gross | **50 symbols gross** | 50 symbols net |
|---|---:|---:|---:|
| gap ≥0.3% | 6.87 | 3.29 | -10.01 |
| gap ≥0.5% | 9.42 | 4.29 | -9.23 |
| gap ≥0.75% | 16.50 | 8.26 | -5.79 |
| gap ≥1.0% | 18.10 | 9.99 | -4.45 |
| gap ≥1.5% | 27.87 | 10.82 | -3.95 |
| fixed 2:1, gap ≥1.0% | 22.05 | 10.92 | -3.50 |
| **gap ≥1.0% + RVOL ≥1.5** | **30.66** | **11.26** | **-3.49** |
| gap ≥1.0% + trend | 17.91 | 7.83 | -6.61 |
| trail 3.0 ATR, gap ≥1.0% | 21.34 | 9.55 | -4.88 |

**Every variant is net negative.** Gross edge fell to roughly a third of the 5-symbol values.

**The diagnosis — it was a lucky draw:**

| Group | Trades | Gross bps | t | Net bps | t |
|---|---:|---:|---:|---:|---:|
| Original 5 symbols | 94 | +30.66 | +3.93 | **+15.78** | +2.02 |
| The other 45 | 608 | +8.26 | +2.75 | **-6.47** | **-2.15** |
| All 50 | 702 | +11.26 | +4.00 | **-3.49** | -1.24 |

RELIANCE, TCS, HDFCBANK, INFY and SBIN happened to be a favourable sample. On the 45 names never used to develop the strategy, net edge is **significantly negative**. This is the cleanest possible demonstration of why 94 trades from 5 correlated names could not settle anything.

**What survives:** the monotonic gap-size relationship is still there (3.29 → 4.29 → 8.26 → 9.99 → 10.82) and the gross t-stats are now *stronger* (up to 4.74) because the sample is 10× larger. The signal is real. But it **plateaus around 11 bps** instead of continuing to climb, so "trade even bigger gaps" does not rescue it — the 1.5% threshold is no better than 1.0%.

**Muhurat sessions ruled out as a cause.** Excluding the two ceremonial sessions (2024-11-01, 2025-10-21) moves gross from 11.26 to 10.95 — no material effect.

**Data quality confirmed clean on all 50:** no duplicates, no OHLC violations, zero gaps matching any split/bonus ratio (largest gap 10.15%, and 2025-04-07 recurs across many names, i.e. a genuine market-wide crash day). The only audit flag was `bad_open=2` on every symbol, which is Muhurat trading, not an error.

### The economics — why 11 bps is not enough

Gross edge is +11.26 bps. Realised cost at the sizes actually traded is 14.75 bps. Net bps/trade at various assumptions:

| Position | 5 bps/leg (modelled) | 3 bps/leg | 2 bps/leg | 1 bps/leg |
|---:|---:|---:|---:|---:|
| ₹70,000 (actual median) | **-9.01** | -5.01 | -3.01 | -1.01 |
| ₹100,000 | -6.99 | -2.99 | -0.99 | +1.01 |
| ₹200,000 | -4.63 | -0.63 | +1.37 | +3.37 |
| ₹500,000 | -3.22 | +0.78 | +2.78 | +4.78 |

**Breakeven slippage at the actual traded size is 0.49 bps per leg** — essentially zero market impact, which is not achievable for a momentum breakout entry that crosses the spread into a moving market. At ~300 trades/year on ₹1 lakh positions: **-₹20,975/yr** at the modelled assumption, **-₹2,975/yr** even at an optimistic 2 bps/leg, **+₹3,025/yr** at a best case of 1 bps/leg.

Turning this profitable requires simultaneously trading ₹2–5 lakh positions *and* achieving near-institutional execution — and the reward for getting both right is a few thousand rupees a year.

---

## 5. The control test — gap direction does carry information

The obvious alternative explanation for §4: big-gap, high-RVOL sessions are just *volatile* sessions, and an ATR trailing stop on a volatile day captures more range no matter which way you enter. If that were the whole story, the "edge" is a volatility artifact that will not survive live.

`backtest/test_gap_controls.py` tests it directly — same qualifying days, same entry levels, same exits, same sizing, only the **direction** changes:

| Configuration | Trades | Gross bps | Net bps |
|---|---:|---:|---:|
| **Real — follow the gap** | 94 | **+30.66** | **+15.78** |
| Control A — random direction, mean of 20 seeds | ~88 | +8.50 | -6.15 |
| Control A — best of 20 seeds | — | +20.91 | +6.39 |
| Control A — worst of 20 seeds | — | -4.43 | -18.42 |
| **Control B — inverted (fade the gap)** | 97 | **-10.95** | **-25.44** |

**The real strategy beats all 20 randomized-direction seeds.** More convincing than the percentile: the result is roughly **symmetric around the random baseline** — real is +22.2 bps above it, inverted is -19.5 bps below it. A volatility artifact would show real ≈ inverted ≈ random. A directional edge shows exactly this mirror pattern, and that is what's here.

Note the honest split: random direction still earns **+8.5 bps gross**, so a real part of the raw edge *is* just volatility capture. The directional signal adds roughly +22 bps on top. Both components have to survive costs, and only their sum does.

This is the strongest evidence in the project so far. It is still one test on 94 trades from 5 correlated mega-caps.

---

## 6. Cost model

Per round trip, NSE cash-equity intraday, 2026 tax year, in `backtest/costs.py`. Verified: **₹103.06 on a ₹50,000 position = 0.2061%.**

| Component | Rate | Side | Share of total (₹50k) |
|---|---|---|---:|
| Brokerage | ₹20 flat or 0.03% of turnover, whichever is lower, per order | Both | 29.1% |
| STT | 0.025% | Sell only | 12.1% |
| Exchange transaction charges | 0.003% | Both | 2.9% |
| SEBI turnover fee | 0.0001% | Both | 0.1% |
| Stamp duty | 0.003% | Buy only | 1.5% |
| GST | 18% on (brokerage + exchange + SEBI) | — | 5.8% |
| **Slippage** (estimate, not official) | **0.05% per leg** | Both | **48.5%** |

**Two changes from round 1, both in `costs.py`:**

- `angel_intraday_commission(order_size, price)` is a **callable** passed to Backtesting.py's `commission`. It charges each order exactly — the ₹20 cap against that order's real turnover, STT on the sell leg only, stamp duty on the buy leg only — instead of halving a round-trip average. This is what fixes defect #2 properly.
- Slippage moved out of commission and into Backtesting.py's `spread` (`SLIPPAGE_PER_LEG = 0.0005`), because slippage moves the fill price rather than charging a fee. `spread` fills buys at `price*(1+spread)` and sells at `price*(1-spread)`.

**The hurdle is size-dependent — 20.6 bps is not a universal constant.** It is the round-trip cost on a ₹50,000 position. Risk-based sizing at 1% of ₹100k equity with 5× MIS leverage produces ₹66k–120k positions, where the realised cost measured in §4 is **13.1–14.9 bps**. Always report the realised figure.

| Position | 5 bps/leg | 3 bps/leg | 2 bps/leg | 1 bps/leg |
|---:|---:|---:|---:|---:|
| ₹50,000 | 20.6 | 16.6 | 14.6 | 12.6 |
| ₹100,000 | 18.3 | 14.3 | 12.3 | 10.3 |
| ₹200,000 | 15.9 | 11.9 | 9.9 | 7.9 |
| ₹500,000 | 14.5 | 10.5 | 8.5 | 6.5 |

**Do not assume the lower slippage numbers.** Keep 5 bps/leg for go/no-go decisions and make measuring true slippage a Phase 2 deliverable. The counter-argument stands: a breakout entry buys into momentum, so its slippage is plausibly *worse* than a passive fill.

---

## 7. Why the universe has to widen

Median daily range on these names is 142–192 bps, so a ~14 bps hurdle is **7–10% of the entire day's high-to-low move**. That is survivable — but only for setups that offer more movement than average, which is exactly what §4 found.

The problem is frequency. At a 1.0% gap threshold with an RVOL filter, a single stock produces **9.4 setups per year**. Across Nifty 50 that is ~470 stock-days/year, roughly 1.9 candidates per session — enough to take the best 1–2 daily and accumulate ~250–400 trades/year, which is the sample size the checklist requires.

This is the structural fix for both sample size and edge concentration, and it converts the design from "trade these 5 tickers" into **"scan 50, trade the ones actually in play"**. It also means Phase 2's runner needs a morning screener rather than a fixed watchlist — confirm that before Phase 2's design is locked.

---

## 8. Locked decisions (unchanged — do not re-litigate)

### Strategy research/charting — Python
TradingView stays out entirely — no official API, can't backtest or paper-trade.

### Historical data source — Angel One SmartAPI
- **jugaad-data ruled out:** EOD only, can't backtest intraday.
- **Angel One SmartAPI historical candle API — chosen**, and validated in practice (§3).
- **Secondary/cross-check only:** `yfinance` intraday (`.NS`) — capped to ~60 days. `jugaad-data` still useful for EOD/corporate-action validation.
- **Noted, not adopted:** `OpenChart` — undocumented lookback depth; NSE killed `nsepython`'s historical endpoint in Jan 2026.

### Backtesting engine — Backtesting.py
- **backtrader ruled out:** unmaintained since Aug 2024.
- **Backtesting.py — chosen, and it has held up well.** The EOD gotcha is handled; the callable-`commission` and `spread` parameters turned out to support the Indian cost model more exactly than expected. The SL-before-TP intrabar assumption still applies — don't take win rates at face value on 5-min bars.
- **vectorbt — revisit at Phase 1.5**, once 50-symbol sweeps become the bottleneck. Validate its SL/TP/EOD behaviour against synthetic known-answer data first.

### Stock/instrument universe
Large-cap, highly liquid NSE cash equity. No small/micro-caps, no options/derivatives. **Amended:** working universe expands from 5 fixed names to the Nifty 50 scan pool (§7).

---

## 9. Go / no-go for Phase 2 — FINAL: NO GO

| # | Criterion | Status on 50 symbols |
|---|---|---|
| 1 | Gross edge ≥ 30 bps/trade at 5 bps/leg slippage | **FAILED** — 11.26 bps |
| 2 | ≥ 200 trades in-sample, ≥ 50 out-of-sample, same sign | trades met (702), **sign FAILED** — net is negative |
| 3 | t-stat > 2.81 on net per-trade edge | **FAILED** — net t = -1.24 (wrong sign) |
| 4 | Beats a randomized-entry benchmark | **MET** — the edge is real, just too small |
| 5 | Survives walk-forward without re-fitting | not run — moot, there is no positive edge to walk forward |
| 6 | Zero overnight positions; defects fixed | **MET** |

**The kill criterion has fired.** It was written as: *"if no variant clears ~25 bps gross, then intraday cash-equity breakout trading on Nifty large-caps does not support a retail cost structure, and the honest move is to stop."* The best variant on the full universe reaches 11.26 bps — **under half the threshold**, with every variant net negative.

**Recommendation: stop this strategy direction. Do not proceed to Phase 2.**

The out-of-sample holdout was never touched and does not need to be — the in-sample result already fails.

### What was actually established

This is a real finding, not a failure to find one:

1. **A genuine directional edge exists in gap continuation** — +11.26 bps gross, t = 4.00 over 702 trades, confirmed by a randomized-direction control that it beat 20/20, with the inverted variant mirroring it negatively. The signal is not noise and not a volatility artifact.
2. **Retail Indian intraday costs exceed it.** ~14 bps round trip against ~11 bps of edge. The constraint that kills it is structural, not a modelling choice.
3. **The binding constraint is the same-day exit.** Median daily range on these names is 142–192 bps, so every round trip spends ~8–10% of the entire day's available movement on costs. A strategy forced to close by 15:15 cannot amortise that over a larger move.

### What would change the answer — scope decisions, not parameter tweaks

None of these are "try another variant". Each changes the project's premise, so they are Ameen's call:

- **Relax the same-day constraint.** Multi-day swing trading amortises the same ~14 bps over moves of several percent rather than a fraction of one. This directly attacks the binding constraint. It abandons "intraday" but keeps cash equity, no derivatives, no leverage risk overnight — a different risk profile that would need its own assessment.
- **Materially cheaper execution.** Breakeven needs ~0.5 bps/leg slippage. Not reachable retail.
- **Accept that the answer is no.** Two years of clean data across 50 stocks and 12 strategies is a solid, well-evidenced negative result. Stopping here costs nothing further and has already avoided losing real money on a strategy that backtested at +15.8 bps on a 5-symbol sample.

**Do not respond to this by testing more intraday variants.** Every additional variant raises the multiple-testing bar and the effect being chased is ~11 bps against a ~14 bps wall. That is the drift this criterion was written to prevent.

## 10. Validation checklist

**Measurement**
- [x] Report gross bps/trade, realised cost, and net bps/trade as the primary metric
- [x] Fixed-fractional risk sizing rather than ~100%-of-equity fills
- [x] t-stat and confidence interval on per-trade edge
- [x] Correct for the number of variants tried (10 in round 2 → |t| > 2.81)

**Sample and regime**
- [ ] Window spans multiple regimes — confirm Aug 2024–Aug 2026 contains a genuine chop regime
- [ ] ≥ 100–200 trades before trusting statistics — **currently 94, the main blocker**
- [ ] Check for lopsided sub-period splits (one month or weekday carrying the result)
- [x] Don't read per-stock results as independent confirmations — 5 correlated mega-caps

**Robustness**
- [ ] Walk-forward validation
- [x] Parameter robustness — the gap-threshold relationship is monotonic, not a spike
- [ ] Out-of-sample holdout, touched **exactly once** — **still untouched, keep it that way**
- [x] Randomized-entry benchmark — passed decisively (§5)
- [ ] Monte Carlo permutation test over the trade sequence

**Sanity**
- [x] Data audit for corporate actions and session integrity (automated in `fetch_universe.py`)
- [x] Assert zero overnight positions
- [ ] Candidate B (VWAP) as cost-model canary — measured at **+0.75 bps gross (t=0.48)**, i.e. no pre-cost edge at all. The source study reports it as profitable *before* costs, so our implementation does not reproduce the source rules and is not currently serving its diagnostic purpose. Worth fixing for that purpose alone, since it is the only check we have that the cost model isn't silently too harsh.

---

## 11. Tasks

**Done**
- [x] SmartAPI historical access, 2 years × 5 large-caps, audited clean
- [x] Cost model built and verified; upgraded to exact per-order charging
- [x] Round 1: 11 strategies tested across 4 families, all ruled out on a per-trade basis
- [x] All 8 implementation defects fixed and verified by invariant checks
- [x] Dynamic Gap + RVOL Momentum strategy built
- [x] Gap-threshold sweep re-run post-fix — monotonic relationship confirmed and strengthened
- [x] Randomized-direction control test — passed decisively

**Next — in this order**
- [ ] **Fetch the Nifty 50 universe** (§12) — blocked on this machine, must run elsewhere
- [ ] Re-run the §4 sweep on the full universe. **This is the make-or-break experiment.**
- [ ] Build the morning screener: rank the universe by gap % and RVOL at 09:15–09:30, take the top 1–2
- [ ] Walk-forward validation once trade count clears 200
- [ ] Monte Carlo permutation test on the trade sequence
- [ ] Touch the 6-month holdout exactly once, at the very end
- [ ] Make the §9 call explicitly, in writing, before any Phase 2 work

---

## 12. Blocker: Angel One is firewalled on the work machine

The 50-symbol fetch cannot run from the OMA Emirates network. `apiconnect.angelone.in` and `margincalculator.angelbroking.com` both resolve to **208.91.112.55** and present a certificate with **`CN=Fortiguard SDNS Blocked Page, O=Fortinet`** — FortiGuard DNS filtering is sinkholing Angel One's domains, almost certainly under a finance/trading category rule. This is a corporate security control and should not be worked around; run the fetch from a personal network instead.

**What to run, from an unblocked network:**

```bash
git pull                                   # or copy the repo across
python data/fetch_universe.py              # ~450 requests, ~6 minutes
```

`data/fetch_universe.py` handles the rest: it resolves symbol → token from Angel One's public scrip master (no hand-maintained token table), requests candles in 90-day chunks (Angel One allows 100 at `FIVE_MINUTE`, so this is ~9 requests per symbol instead of 493), backs off hard on rate-limit responses, skips symbols already downloaded, and audits every file it writes.

**What comes back:** `data/<SYMBOL>_5min.csv` for each name, same schema as the existing five (`datetime,open,high,low,close,volume`, tz-aware IST), plus `data/universe_fetch_report.txt`.

**Check the report before backtesting anything.** The audit flags duplicates, OHLC violations, sessions not starting at 09:15, and — most importantly — overnight gaps above 15%, which almost always mean an **unadjusted split or bonus**. One of those in the data fabricates an enormous fake signal for a gap strategy, which is exactly the strategy under test.

The universe list in `data/nifty50.json` is a plain symbol list; **verify it against the current Nifty 50 constituents** before relying on it, since index membership changes at semi-annual reviews and a dropped name introduces survivorship bias. The fetcher reports any symbol it cannot resolve.

---

## 13. Environment note

The `.venv` was created on a different machine (`E:\trading`, base interpreter `C:\Python313`) and its `pyvenv.cfg` pointed at a path that doesn't exist here, so `.venv\Scripts\python.exe` refused to launch. Repointed to `C:\Users\ameenur.r.OMAEMIRATES\AppData\Local\Programs\Python\Python313` — same 3.13.3, so the existing `site-packages` were kept. Verified: pandas 3.0.5, backtesting 0.6.6, numpy 2.5.2, SmartApi, pyotp, dotenv, pandas_market_calendars, logzero, websocket-client, bokeh, requests. Original config saved as `.venv/pyvenv.cfg.bak`.

`backoff_handoff.md` still describes the tree as `e:/trading/` — cosmetic, but its paths won't resolve here.

---

## 14. File map (Phase 1)

| File | Purpose |
|---|---|
| `strategies/session.py` | Session structure, day-aware ATR, risk sizing — the shared fixes for defects #1, #5, #6, #7 |
| `strategies/orb_strategy.py` | Candidate A, post-fix |
| `strategies/gap_rvol_strategy.py` | Dynamic Gap + RVOL Momentum (round 2) |
| `backtest/costs.py` | Indian cost model + `angel_intraday_commission` callable |
| `backtest/verify_fixes.py` | Before/after comparison + invariant checks for the 8 defects |
| `backtest/test_gap_rvol.py` | Gap-threshold and filter sweep |
| `backtest/test_gap_controls.py` | Randomized-direction and inverted-direction controls |
| `data/fetch_universe.py` | Chunked 50-symbol fetcher with token resolution and audit |
| `data/nifty50.json` | Universe symbol list |

## Reference code

- [marketcalls/vectorbt-backtesting-skills](https://github.com/marketcalls/vectorbt-backtesting-skills) — Indian-market cost model, look-ahead-safe breakout templates, NSE session-window pattern, walk-forward template. Built for vectorbt, useful as reference regardless of engine.

## Verification

- Backtest reports reviewed manually — as **gross bps / realised cost / net bps**, never total return alone.
- §10 checklist worked through, not eyeballed.
- §9 go/no-go stated explicitly in writing, including willingness to invoke the kill criterion.
