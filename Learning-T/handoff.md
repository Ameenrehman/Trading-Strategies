# Handoff — NSE Systematic Trading (delivery/CNC momentum)

Read this first if you're picking this project up in a fresh conversation with no prior context.

## What this is

Ameen is building an automated systematic trading system for the Indian stock market (NSE): Python strategy backtesting → paper trading → live order execution via Angel One. Free tools only, runs locally where possible. Long-only cash equity, no options/derivatives, no small-caps.

**The product changed.** It began as intraday (MIS); intraday was tested across 12 strategies and rejected on cost grounds, and the project is now **delivery (CNC)** — multi-week holds where a ~39 bps round trip amortises over a large enough move.

## Current status (as of 2026-08-22)

- **Phase 0** — done. SmartAPI auth + TOTP working, venv running.
- **Phase 1 (intraday) — COMPLETE AND REJECTED.** 12 strategies, 4 families, 50 Nifty stocks, 2 years of clean 5-minute data. A genuine directional edge was found (+11.26 bps gross, t = 4.00 over 702 trades, beating 20/20 randomized-direction controls) and shown to be **smaller than the ~14 bps it costs to trade**. Breakeven needed 0.49 bps/leg slippage. The pre-registered kill criterion fired. No money was risked.
- **Phase 1b (delivery/CNC momentum) — COMPLETE.** 205 Nifty 200 symbols, 15.0 years of daily bars. 16/16 known-answer sanity checks pass.
  - **+12.18%/yr over equal-weight buy-and-hold after delivery costs** (29.22% vs 17.04% CAGR), Sharpe 1.42 vs 1.07, drawdown no worse.
  - **Controls passed 20/20** — momentum beat every random-selection seed, and the bottom decile is symmetrically worse. Same design that killed the intraday phase.
  - **Criterion 5 (walk-forward): PASS** — 7/9 out-of-sample windows, mean +17.07%/yr, t = 2.47, still +12.26%/yr excluding the best window.
  - **Criterion 6 (recent 5 years): PASS at +8.92%/yr.**
  - **Permutation test: 0 of 400** time-shuffled runs matched the real edge (z = 6.73), clearing the Bonferroni bar for 14 variants.
  - **All six pre-registered criteria pass.**
- **Phase 2 (local paper trading) — BUILT, REVIEWED, FIXED, READY TO RUN FORWARD.**
  - `live/portfolio_state.py` — the single definition of `positions.json`. The generator and the broker previously wrote two different schemas to the same file; see `phase-2-paper-trading.md` for both failure directions.
  - `live/paper_broker.py` — simulated fills against read-only SmartAPI quotes. **Refuses to fill on or before the signal date.**
  - `live/track_performance.py` — NAV against equal-weight buy-and-hold over the same window, plus a cost and slippage audit reported with its standard error.
  - `live/dashboard.py` — the book as one self-contained local HTML page (`python live/dashboard.py --open`). The HTML is gitignored as generated output; the underlying `positions.json` and `paper_ledger.csv` are committed while the book is simulated, and must be re-ignored before Phase 3.
  - `live/test_paper_broker.py` — 2/2 passing.
  - **Five defects were found and fixed in review.** One was a look-ahead that filled at an open preceding the signal, measuring −5.3 bps of slippage and reading as a clean pass. Written up in full in `phase-2-paper-trading.md`.
- **The slippage assumption is now MEASURED, and Phase 2 was not the thing that measured it.** `backtest/test_execution_gap.py` over 1,740 historical legs: net **+0.8 bps/leg** across buys and sells, momentum-specific excess **+4.5 bps** (t = 1.44, not significant) against the **5 bps assumed**. The cost model is conservative. Per-leg noise is 112 bps, so paper trading would need ~13 years to resolve this — judge Phase 2 on pipeline correctness and forward record, not on its slippage mean. Market impact remains unmeasured and does need live orders.
- **Data is now committed** — `data/daily/` (205 symbols × 15 yrs) and `data/intraday_5min/` (50 × 2 yrs). Everything reproduces with no network and no credentials.
- **Nothing has touched live money.** No live capital risked.

## Read in this order

1. `00-overview.md` — context, architecture diagrams, folder structure, master decisions table
2. `phase-0-setup.md` — accounts & environment
3. `phase-1b-delivery-momentum.md` — delivery momentum methodology & findings
4. `phase-1-backtesting.md` — the completed intraday phase and why it was rejected
5. `phase-2-paper-trading.md` — local paper trading workflow and slippage measurement
6. `phase-3-live-trading.md` / `phase-4-hardening.md` — future live deployment roadmap

## Key decisions already made (don't re-litigate unless something concretely breaks)

- **Broker**: Angel One SmartAPI
- **Backtesting data source**: Angel One SmartAPI historical candle API — NOT `jugaad-data` (verified EOD-only, can't backtest intraday at all)
- **Backtesting engine**: Custom portfolio rebalancer in `backtest/portfolio.py` with exact delivery cost models
- **Paper Trading**: Custom local paper broker via read-only SmartAPI quote endpoints (not TradingView / not external sandboxes)
- **SEBI compliance**: Retail algo framework in force since April 1, 2026. Static IP + OAuth + 2FA required only for live order-placement API access (Phase 3), not for read-only paper trading.

## How to operate Phase 2 (Forward Paper Trading)

1. **At Market Close (15:30 IST) on Rebalance Dates**:
   ```bash
   python live/generate_orders.py
   ```
2. **Next Morning (09:15–09:30 IST) at Market Open**:
   ```bash
   python live/paper_broker.py
   ```
   Must be a **later day** than step 1 — the broker enforces this.
3. **Daily Performance & Slippage Tracking**:
   ```bash
   python live/track_performance.py
   python live/dashboard.py --open      # same thing, as a page
   ```

Do not fund an account for Phase 3 until paper trading has accumulated a meaningful track record of measured slippage across multiple rebalance dates.
