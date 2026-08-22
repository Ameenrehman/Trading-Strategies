# Handoff — Phase 1 Backtesting & Strategy Analysis

**Date**: 2026-08-22
**Project**: Automated NSE Intraday Trading Bot (Cash-Equity, Large-Cap, Zero Derivatives)
**Status**: Phase 0 complete | **Phase 1 (intraday) COMPLETE — rejected** | **Phase 1b (delivery/CNC momentum) built, awaiting data**

> Supersedes the original version of this file, which ranked strategies by total return. That metric mostly measured trade frequency and led to two wrong conclusions (see §2). The full reasoning lives in `Learning-T/phase-1-backtesting.md` — this file is the summary.

---

## 1. Where things stand

- **Phase 0 verified.** SmartAPI auth + automated TOTP working, credentials in `.env`, local venv running.
- **Data.** 2 years of 5-minute OHLCV across the **full Nifty 50** (498 sessions, ~37,140 bars per symbol, 108 MB). **Audited clean on all 50** — no duplicates, no OHLC violations, and specifically **no unadjusted corporate actions**, which would have fabricated a fake gap-strategy edge.
- **Cost model.** Exact 2026 Indian intraday costs, now charged **per order** rather than as a flat fraction: ₹103.06 round-trip on ₹50,000 = **0.2061%**.
- **Round 1** — 11 strategies across 4 families, all ruled out. Best gross edge 7.7 bps vs a 20.6 bps hurdle.
- **Round 2** — 8 implementation defects fixed, new Dynamic Gap + RVOL Momentum strategy built. Best variant: **+30.7 bps gross, +15.8 bps net per trade**, and it **beats all 20 randomized-direction control seeds**.
- **Round 3** — the same strategy on all 50 symbols: **+11.3 bps gross, -3.5 bps net**. Every variant net negative. **Kill criterion fired.**
- The 50-symbol fetch had to run off the corporate network (Angel One is firewalled here) — see `RUN_AT_HOME.md`.

---

## 2. The measurement correction

The original version of this file reported total 2-year return (-56.3%, -53.5%, -8.5% …) and called Candidate C "the strongest performer". Every round-1 backtest put ~100% of equity into each trade, so total return ≈ per-trade edge compounded over the trade count. **That ranks strategies by how little they trade, not by how good their signals are.**

Measuring per trade instead, at zero cost, changes the conclusions:

| Strategy | Trades | Gross bps/trade | t | Net @ 20.6 bps |
|---|---:|---:|---:|---:|
| Gap + ORB continuation (≥0.5%) | 343 | +7.67 | 1.95 | -12.94 |
| Trend Gap + 20 EMA trail | 560 | +7.27 | 2.59 | -13.34 |
| NR7 / Inside-Bar | 458 | +5.04 | 1.92 | -15.57 |
| Prev-day High/Low | 1677 | +3.58 | 2.35 | -17.03 |
| VWAP breakout | 1954 | +0.75 | 0.48 | -19.86 |
| Supertrend | 1691 | +0.52 | 0.32 | -20.09 |
| Trend+Vol filtered ORB | 913 | -0.14 | -0.06 | -20.75 |
| Gap fade | 346 | -0.17 | -0.05 | -20.78 |
| **Naive ORB 30m** | 1942 | **-0.88** | -0.48 | -21.49 |
| VWAP pullback | 2114 | -2.05 | -1.60 | -22.66 |
| EMA momentum | 1328 | -2.68 | -1.55 | -23.30 |

**Naive ORB has no edge at all** — not "an edge destroyed by costs". Gross -0.88 bps with t = -0.48 over 1,942 trades. The whole -56% was toll: 388 trades × 20.6 bps.

**Two claims from the original to drop:**

- *"Filtering for >0.5% gaps eliminated ~85% of chop sessions."* Measured: a >0.5% gap occurs on **26–48%** of days depending on the stock. The filter removes 52–74%, not 85%.
- *"TCS was profitable (+1.62%)."* Selection bias — 11 strategies × 5 stocks, and one or two landing marginally positive is what a zero-edge process produces. Round 3 confirmed this decisively: the original 5 names were simply a favourable draw.

---

## 3. Implementation defects — found, fixed, verified

Round 1's code had eight defects. All fixed; `backtest/verify_fixes.py` asserts the invariants.

| # | Defect | Verified after fix |
|---|---|---|
| 1 | No position sizing (~100% of equity per trade) | risk/trade **0.98%** of equity |
| 2 | Cost assumed ₹50k while positions were ~₹100k | per-order callable, exact at any size |
| 3 | Dead stop-loss branch → realised RR was **1.87**, not 2.0 | realised RR **2.000** |
| 4 | Session burned when an order was rejected | one entry per session, 0 violations |
| 5 | ATR counted the overnight gap as intraday range | day-aware ATR |
| 6 | **4 positions leaked overnight** on truncated feed days | **0 overnight positions** |
| 7 | Opening range keyed to bar count, not clock time | timestamp-keyed |
| 8 | Entry filled at bar close, not the breakout level | resting stop orders |

Effect on ORB: gross **-0.82 → +0.44 bps/trade (+1.26)**. As expected — the defects were worth a couple of bps and ORB is still dead. The point was to make round 2 trustworthy.

---

## 4. Round 2 — Dynamic Gap + RVOL Momentum (5 symbols — later superseded by §6)

Trade only sessions that gapped, enter in the gap direction at the opening-range extreme, hold with an ATR chandelier trailing stop, size by fixed-fractional risk. `cost` below is **realised** at the sizes actually traded, not the flat ₹50k figure:

| Variant | Trades | Gross bps | gross t | Cost | **Net bps** | net t |
|---|---:|---:|---:|---:|---:|---:|
| gap ≥0.3%, trail 2.0 ATR | 690 | 6.87 | 3.22 | 13.12 | -6.25 | -2.93 |
| gap ≥0.5% | 422 | 9.42 | 3.25 | 13.44 | -4.01 | -1.39 |
| gap ≥0.75% | 234 | 16.50 | 3.76 | 14.05 | +2.45 | 0.56 |
| gap ≥1.0% | 161 | 18.10 | 3.23 | 14.34 | +3.76 | 0.67 |
| gap ≥1.5% | 64 | 27.87 | 2.93 | 14.48 | +13.39 | 1.41 |
| **gap ≥1.0% + RVOL ≥1.5** | **94** | **30.66** | **3.93** | **14.88** | **+15.78** | **2.02** |

**The monotonic gap-size relationship survived the rewrite and strengthened.** It is a mechanism, not a parameter spike: cost is fixed per trade, so edge has to be measured against how much movement the setup offers.

**The realised cost hurdle is ~13–15 bps, not 20.6.** 20.6 is the cost on a ₹50,000 position; risk-based sizing produces ₹66k–120k positions where the ₹20 brokerage cap stops binding.

---

## 5. The control test — the edge is directional, not a volatility artifact

Big-gap, high-RVOL days are also *volatile* days, and a trailing stop on a volatile day captures range regardless of direction. If that were the whole story, the edge is an artifact. Same days, same levels, same exits — only direction changes:

| Configuration | Trades | Gross bps | Net bps |
|---|---:|---:|---:|
| **Real — follow the gap** | 94 | **+30.66** | **+15.78** |
| Random direction (mean of 20 seeds) | ~88 | +8.50 | -6.15 |
| Random direction (best seed) | — | +20.91 | +6.39 |
| **Inverted — fade the gap** | 97 | **-10.95** | **-25.44** |

Real beats **20/20** random seeds, and the result is roughly **symmetric around the random baseline** (+22.2 above, -19.5 below). A volatility artifact would show real ≈ inverted ≈ random. This is what a genuine directional edge looks like.

Honest caveat: random direction still earns +8.5 bps gross, so part of the raw edge really is volatility capture. Direction adds ~22 bps on top.

---

## 6. Round 3 — 50 symbols, and the verdict

The 5-symbol result rested on 94 trades from correlated mega-caps. Widening to the full Nifty 50 (702 trades, same code, same parameters) collapsed it:

| Group | Trades | Gross bps | t | Net bps | t |
|---|---:|---:|---:|---:|---:|
| Original 5 symbols | 94 | +30.66 | +3.93 | **+15.78** | +2.02 |
| The other 45 | 608 | +8.26 | +2.75 | **-6.47** | **-2.15** |
| **All 50** | **702** | **+11.26** | **+4.00** | **-3.49** | -1.24 |

The original 5 were a favourable draw. On the 45 names never used to build the strategy, net edge is **significantly negative**. All 10 variants are net negative on the full universe.

Data was clean: no duplicates, no OHLC violations, no split/bonus artifacts across all 50. The two `bad_open` flags per symbol are Muhurat sessions; excluding them moves gross 11.26 → 10.95, i.e. nothing.

### Verdict: NO GO — the kill criterion fired

Gross +11.26 bps vs a realised ~14.75 bps hurdle. Breakeven needs **0.49 bps/leg** slippage — effectively zero market impact. At ~300 trades/yr on ₹1L positions: **-₹20,975/yr** as modelled, **+₹3,025/yr** even at an unrealistic 1 bps/leg best case.

**What is genuinely established:**

1. **A real directional edge exists** — +11.26 bps gross, t = 4.00, confirmed against a randomized-direction control it beat 20/20. Not noise, not a volatility artifact.
2. **Retail Indian intraday costs exceed it.** Structural, not a modelling choice.
3. **The binding constraint is the same-day exit.** Median daily range is 142–192 bps, so each round trip burns ~8–10% of the day's entire available movement.

**What would change the answer — scope decisions, not parameter tweaks:**

- **Relax the same-day constraint.** Multi-day swing trading amortises the same ~14 bps over percent-scale moves instead of a fraction of one. Directly attacks the binding constraint; keeps cash equity and no derivatives, but is a different risk profile needing its own assessment.
- **Materially cheaper execution.** Needs ~0.5 bps/leg. Not reachable retail.
- **Accept the negative result.** 12 strategies, 50 stocks, 2 years of clean data. Stopping costs nothing more and has already avoided risking real money on something that backtested at +15.8 bps on 5 symbols.

**Do not respond by testing more intraday variants.** Every variant raises the multiple-testing bar, and the effect being chased is ~11 bps against a ~14 bps wall. That is exactly the drift the kill criterion was written to prevent.

---

## 9. File map

```
Learning-T/
├── RUN_AT_HOME.md              # fetch procedure for the unblocked network
├── backoff_handoff.md          # this file
├── requirements.txt
├── Learning-T/                 # planning docs
│   ├── 00-overview.md
│   ├── handoff.md              # read first in a fresh session
│   ├── phase-0-setup.md
│   ├── phase-1-backtesting.md  # intraday: results, defects, why it was rejected
│   ├── phase-1b-delivery-momentum.md  # CURRENT: delivery momentum
│   └── phase-2..4-*.md
├── strategies/
│   ├── momentum_xs.py          # cross-sectional momentum + trend filter (CURRENT)
│   ├── session.py              # session structure, day-aware ATR, risk sizing
│   ├── orb_strategy.py         # Candidate A, post-fix (rejected)
│   └── gap_rvol_strategy.py    # Dynamic Gap + RVOL Momentum (rejected)
├── live/
│   └── generate_orders.py      # the actual buy/sell list, shares backtest signal code
├── backtest/
│   ├── costs.py                # intraday AND delivery cost models
│   ├── portfolio.py            # monthly-rebalance portfolio backtester
│   ├── test_portfolio_sanity.py    # 14 known-answer checks - run first
│   ├── test_momentum.py            # momentum vs benchmark
│   ├── test_momentum_controls.py   # random-selection / bottom-decile controls
│   ├── verify_fixes.py         # before/after + invariant checks
│   ├── test_gap_rvol.py        # gap threshold / filter sweep
│   ├── test_gap_controls.py    # randomized-direction controls
│   ├── validate.py             # 6-point overfitting suite (not yet run)
│   ├── run_backtest.py         # ORB CLI runner
│   └── results/
└── data/
    ├── fetch_universe.py       # chunked fetcher, 5-min AND daily, + audit
    ├── nifty200.json           # delivery universe (VERIFY against live NSE list)
    ├── nifty50.json            # intraday universe
    ├── fetch_historical.py     # original day-by-day fetcher
    ├── corporate_actions.py    # detects unadjusted splits/demergers/relistings
    ├── daily/                  # 205 symbols x 15 yrs (delivery)
    └── intraday_5min/          # 50 symbols x 2 yrs (intraday, rejected)
```## 7. Where the project went next — delivery (CNC), not intraday

The intraday result diagnosed its own constraint precisely: **the same-day exit**. Median daily range is 142–192 bps, so each round trip burns 8–10% of the day's entire available movement. Holding longer attacks that directly, because moves scale with roughly sqrt(time) while cost is paid once per trade.

The catch is that **delivery costs 2.1x intraday** — STT is 0.1% on *both* legs instead of 0.025% sell-only, and DP charges add a flat Rs.20 per scrip on the sell. So 2-5 day swings are the worst of both worlds. The viable zone is multi-week holds:

| Hold | Median move | Delivery cost as % of move |
|---:|---:|---:|
| 1 day | 82 bps | 47.4% |
| 20 days | 418 bps | 11.1% |
| ~70 days | ~800 bps | **~6%** |

**Strategy:** 12-1 cross-sectional momentum (12-month return skipping the recent month), filtered to names above their 200-DMA, top 20 equal-weight, monthly rebalance on the Nifty 200.

**Exits:** no stop-loss, no take-profit — the rebalance is the exit. A name is sold when it drops out of the top 20 or falls below its 200-DMA. The 200-DMA filter is the systematic stop; hard stops and daily trend exits are implemented as *testable options*, not assumptions.

**Measured annual cost drag: 0.94%/yr** at the monthly baseline (516%/yr turnover, Rs.10L book), against a measured 12.18%/yr edge over the benchmark. That is the structural difference from intraday, where cost exceeded the entire edge. Minimum viable capital is around Rs.5L — below that, fixed Rs.20 brokerage and Rs.20 DP per scrip start to dominate.

**Rebalance frequency is not turnover.** Measured on real data: monthly baseline = 516%/yr turnover and 0.94%/yr cost; daily with no rank buffer = 2,624%/yr and 4.85%/yr, giving up ~4.8%/yr of CAGR. With `--rank-buffer 20` a daily schedule turns over *less* than monthly (497%, 0.90%/yr), so a daily buy list is viable — it just requires the buffer.

**Status: first real result in.** 205 Nifty 200 symbols, 15.0 years of daily bars, 16/16 known-answer sanity checks.

| | CAGR | Sharpe | Max DD | Turnover/yr | Cost/yr |
|---|---:|---:|---:|---:|---:|
| **Momentum** 12-1 top 20 +200DMA | **29.22%** | **1.42** | -37.4% | 516% | 0.94% |
| Equal-weight buy & hold | 17.04% | 1.07 | -37.8% | 8% | 0.03% |
| Random selection (mean, 20 seeds) | 15.38% | 0.95 | -37.1% | — | — |
| Bottom decile by momentum | 12.21% | 0.75 | -41.8% | — | — |

**Pre-registered go/no-go, scored:** (1) beat buy-and-hold by >=3%/yr after costs — **+12.18%/yr PASS**; (2) higher Sharpe, drawdown no worse — **PASS**; (3) beat >=19/20 random seeds — **20/20 PASS**; (4) bottom decile symmetrically worse — **PASS**; (5) survive walk-forward — **7/9 windows, +17.07%/yr, t=2.47, PASS**; (6) hold up in the recent 5 years — **+8.92%/yr PASS**.

**Permutation test:** shuffling the time-ordering of returns (preserving each symbol's distribution and each day's cross-section) collapses the edge from +15.92%/yr to a null centred on +0.41%. **0 of 400** shuffled runs matched the real edge; z = 6.73. Empirical p = 0.0025 clears the Bonferroni bar of 0.05/14 = 0.00357 on its own.

**The most decision-relevant result is negative.** Selecting the best in-sample variant at each walk-forward fold and applying it to the next unseen window **lost** to the fixed baseline: 3/9 windows, mean -3.41%/yr, with six different variants winning across nine folds. The 14-variant sweep was fitting noise. Trade the pre-registered baseline, not the sweep winner.

**Verdict: all pre-registered criteria pass; still not cleared for capital.** Three reasons, none of which another backtest can address: the holdout was observed before it was sealed (the first real-data run had no holdout handling and spanned 2011-2026); slippage is assumed at 5 bps/leg and never measured; and survivorship bias is inherent to a universe defined by today's index membership. The intraday phase looked convincing on 5 symbols and collapsed on 50 — that is the failure this sequence exists to prevent.

**Three defects found once real data arrived:** (a) cost drag was computed against *initial* capital rather than the running book, overstating it 12x on a portfolio that compounded 42.8x — the equity curve was always correct, but every published cost table was wrong; (b) three symbols carried unadjusted corporate actions (ADANIENT demerger -80.9%, PATANJALI/Ruchi Soya relisting +406.2%, YESBANK moratorium -56.1%), which for a strategy ranking on trailing 12-month returns puts a phantom stock at the top or bottom of the ranking for twelve consecutive rebalances. (c) `run_portfolio`'s `start`/`end` sliced the price history rather than the trading window, starving any lookback shorter than the window and silently reporting 0% CAGR -- this is what produced the earlier bogus "criterion 6 FAIL at +2.04%/yr". All three are fixed and regression-tested (16/16 sanity checks).

Full detail: `Learning-T/phase-1b-delivery-momentum.md`.

## 7b. Immediate next step

Phase 1b validation is **complete** — all six criteria, plus permutation and Bonferroni. Everything reproduces offline. What remains cannot be answered by a backtest:

1. **Paper trade forward.** It is the only genuinely out-of-sample test still available (the holdout was observed before it was sealed), and it measures **slippage** — the largest unverified assumption in the model. The cost model assumes 5 bps/leg; the current buy list holds names near Rs.14 where that may be badly optimistic.
2. Resolve `GUJGASLTD` and `LTIM` in the scrip-master lookup; verify `nifty200.json` against the live NSE list.
3. Decide whether the compromised holdout is worth re-cutting.

```bash
python backtest/test_portfolio_sanity.py     # 16/16 or nothing else means anything
python data/corporate_actions.py             # what gets repaired, and why
python backtest/test_momentum.py             # main result + year-by-year
python backtest/test_momentum_controls.py    # the controls
python backtest/walk_forward.py              # criterion 5 + the selection test
python backtest/test_permutation.py          # permutation + Bonferroni
python live/generate_orders.py --force --dry-run --rank-buffer 20
```

**The out-of-sample holdout has never been touched. Keep it that way.**


