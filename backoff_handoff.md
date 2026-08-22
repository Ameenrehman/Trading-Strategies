# Handoff — Phase 1 Backtesting & Strategy Analysis

**Date**: 2026-08-22
**Project**: Automated NSE Intraday Trading Bot (Cash-Equity, Large-Cap, Zero Derivatives)
**Status**: Phase 0 complete | Phase 1 — round 2 complete, one promising strategy, **not validated**

> Supersedes the original version of this file, which ranked strategies by total return. That metric mostly measured trade frequency and led to two wrong conclusions (see §2). The full reasoning lives in `Learning-T/phase-1-backtesting.md` — this file is the summary.

---

## 1. Where things stand

- **Phase 0 verified.** SmartAPI auth + automated TOTP working, credentials in `.env`, local venv running.
- **Data.** 2 years of 5-minute OHLCV, 493 trading days, 5 Nifty 50 names (`SBIN`, `RELIANCE`, `TCS`, `HDFCBANK`, `INFY`), 36,942 bars each. **Audited clean** — no duplicates, no OHLC violations, and specifically **no unadjusted corporate actions**, which would have fabricated a fake gap-strategy edge.
- **Cost model.** Exact 2026 Indian intraday costs, now charged **per order** rather than as a flat fraction: ₹103.06 round-trip on ₹50,000 = **0.2061%**.
- **Round 1** — 8 strategy variants, all ruled out. Best gross edge 7.7 bps vs a 20.6 bps hurdle.
- **Round 2** — 8 implementation defects fixed, new Dynamic Gap + RVOL Momentum strategy built. Best variant: **+30.7 bps gross, +15.8 bps net per trade**, and it **beats all 20 randomized-direction control seeds**.
- **Blocked** — the decisive 50-symbol test can't run here. Angel One is firewalled on the work network. See `RUN_AT_HOME.md`.

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
| Supertrend | 1691 | +0.52 | 0.32 | -20.09 |
| Gap fade | 346 | -0.17 | -0.05 | -20.78 |
| **Naive ORB 30m** | 1942 | **-0.88** | -0.48 | -21.49 |
| EMA momentum | 1328 | -2.68 | -1.55 | -23.30 |

**Naive ORB has no edge at all** — not "an edge destroyed by costs". Gross -0.88 bps with t = -0.48 over 1,942 trades. The whole -56% was toll: 388 trades × 20.6 bps.

**Two claims from the original to drop:**

- *"Filtering for >0.5% gaps eliminated ~85% of chop sessions."* Measured: a >0.5% gap occurs on **26–48%** of days depending on the stock. The filter removes 52–74%, not 85%.
- *"TCS was profitable (+1.62%)."* Selection bias — 8 strategies × 5 stocks = 40 backtests, and one or two landing marginally positive is what a zero-edge process produces.

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

## 4. Round 2 — Dynamic Gap + RVOL Momentum

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

## 5. The control test — the most important result so far

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

## 6. Go / no-go scorecard — 3 of 6 met

| # | Criterion | Status |
|---|---|---|
| 1 | Gross edge ≥ 30 bps/trade | **MET** — 30.66 |
| 2 | ≥200 trades in-sample, ≥50 out-of-sample | **NOT MET** — 94 in-sample, 0 OOS |
| 3 | Net t > 2.81 (Bonferroni, 10 variants) | **NOT MET** — net t = 2.02 |
| 4 | Beats randomized-entry benchmark | **MET** — 20/20 seeds |
| 5 | Survives walk-forward | **NOT TESTED** |
| 6 | Zero overnight positions, defects fixed | **MET** |

The two blocking gaps are the same gap: **sample size**. 94 trades from 5 correlated mega-caps cannot settle this. The 50-symbol universe closes it.

**Do not start Phase 2 on these numbers.**

---

## 7. Next step

**Run `data/fetch_universe.py` from an unblocked network** — see `RUN_AT_HOME.md` for the full procedure. ~450 requests, ~6 minutes, with automatic token resolution and a data-integrity audit.

Then re-run `backtest/test_gap_rvol.py` and `backtest/test_gap_controls.py` on 50 symbols and check three things: does the monotonic gap relationship hold, does net t clear ~2.8, does the control still pass.

**The out-of-sample holdout has not been touched. Keep it that way** until the strategy is final.

---

## 8. Blocker on the work machine

```
apiconnect.angelone.in            -> 208.91.112.55
margincalculator.angelbroking.com -> 208.91.112.55
TLS cert: CN=Fortiguard SDNS Blocked Page, O=Fortinet
```

FortiGuard DNS filtering sinkholes Angel One's domains on the OMA Emirates network. Corporate security control — run elsewhere or request an IT exception, don't route around it. Phase 3 already assumes an AWS `ap-south-1` static-IP host, so live trading was never going to run from here anyway.

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
│   ├── phase-1-backtesting.md  # FULL detail: results, defects, validation, go/no-go
│   └── phase-2..4-*.md
├── strategies/
│   ├── session.py              # session structure, day-aware ATR, risk sizing
│   ├── orb_strategy.py         # Candidate A, post-fix
│   └── gap_rvol_strategy.py    # Dynamic Gap + RVOL Momentum (round 2)
├── backtest/
│   ├── costs.py                # Indian cost model + per-order commission callable
│   ├── verify_fixes.py         # before/after + invariant checks
│   ├── test_gap_rvol.py        # gap threshold / filter sweep
│   ├── test_gap_controls.py    # randomized-direction controls
│   ├── validate.py             # 6-point overfitting suite (not yet run)
│   ├── run_backtest.py         # ORB CLI runner
│   └── results/
└── data/
    ├── fetch_universe.py       # chunked 50-symbol fetcher + audit
    ├── nifty50.json            # universe list (VERIFY against live NSE list)
    ├── fetch_historical.py     # original day-by-day fetcher
    └── *_5min.csv              # 5 symbols so far
```
