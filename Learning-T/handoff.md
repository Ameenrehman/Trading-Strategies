# Handoff — NSE Systematic Trading (delivery/CNC momentum)

Read this first if you're picking this project up in a fresh conversation with no prior context.

## What this is

Ameen is building an automated systematic trading system for the Indian stock market (NSE): Python strategy backtesting → paper trading → live order execution via Angel One. Free tools only, runs locally where possible. Long-only cash equity, no options/derivatives, no small-caps.

**The product changed.** It began as intraday (MIS); intraday was tested across 12 strategies and rejected on cost grounds, and the project is now **delivery (CNC)** — multi-week holds where a ~39 bps round trip amortises over a large enough move.

## Current status (as of 2026-08-22)

- **Phase 0** — done. SmartAPI auth + TOTP working, venv running.
- **Phase 1 (intraday) — COMPLETE AND REJECTED.** 12 strategies, 4 families, 50 Nifty stocks, 2 years of clean 5-minute data. A genuine directional edge was found (+11.26 bps gross, t = 4.00 over 702 trades, beating 20/20 randomized-direction controls) and shown to be **smaller than the ~14 bps it costs to trade**. Breakeven needed 0.49 bps/leg slippage. The pre-registered kill criterion fired. No money was risked.
- **Phase 1b (delivery/CNC momentum) — CURRENT, first real result in.** 205 Nifty 200 symbols, 15.0 years of daily bars. 16/16 known-answer sanity checks pass.
  - **+12.18%/yr over equal-weight buy-and-hold after delivery costs** (29.22% vs 17.04% CAGR), Sharpe 1.42 vs 1.07, drawdown no worse.
  - **Controls passed 20/20** — momentum beat every random-selection seed, and the bottom decile is symmetrically worse. Same design that killed the intraday phase.
  - **Criterion 5 (walk-forward): PASS** — 7/9 out-of-sample windows, mean +17.07%/yr, t = 2.47, still +12.26%/yr excluding the best window.
  - **Criterion 6 (recent 5 years): PASS at +8.92%/yr.** An earlier run reported this as a +2.04%/yr FAIL; that was a backtester defect, not the strategy.
  - **Permutation test: 0 of 400** time-shuffled runs matched the real edge (z = 6.73), clearing the Bonferroni bar for 14 variants.
  - **All six pre-registered criteria pass. Still not cleared for capital** — the holdout is compromised, slippage is assumed rather than measured, and survivorship bias cannot be removed by any backtest.
  - **Most decision-relevant finding is negative:** picking the best in-sample variant each fold *lost* to the fixed baseline by 3.41%/yr across 9 windows. The 14-variant sweep was fitting noise; trade the pre-registered baseline.
- **Data is now committed** — `data/daily/` (205 symbols × 15 yrs) and `data/intraday_5min/` (50 × 2 yrs). Everything reproduces with no network and no credentials.
- **Phases 2–4** — decisions locked but need revisiting: dropping intraday removes most of the real-time engineering.
- **Nothing has touched live markets.** No orders, no cloud resources, no paper trading. The out-of-sample holdout has never been touched.

## Read in this order

1. `00-overview.md` — context, architecture diagrams, folder structure, master decisions table
2. `phase-0-setup.md` — accounts & environment (do this first, it's a hard blocker for Phase 1 too)
3. `phase-1b-delivery-momentum.md` — **current focus**
4. `phase-1-backtesting.md` — the completed intraday phase and why it was rejected
4. `phase-2-paper-trading.md` / `phase-3-live-trading.md` / `phase-4-hardening.md` — locked decisions, lighter detail

## Key decisions already made (don't re-litigate unless something concretely breaks)

- **Broker**: Angel One SmartAPI
- **Backtesting data source**: Angel One SmartAPI historical candle API — NOT `jugaad-data` (verified EOD-only, can't backtest intraday at all)
- **Backtesting engine**: `Backtesting.py` — NOT `backtrader` (unmaintained since 2024) — NOT `vectorbt` (open bugs specifically on intraday SL/TP + end-of-day-exit with multiple entries)
- **Bridge**: custom-built from scratch (not OpenAlgo) — full control/understanding over anything that can place a real order
- **Live hosting**: AWS EC2 free tier + Elastic IP, `ap-south-1` region
- **Instrument scope**: NSE cash equity only, large-cap/liquid (Nifty 50/100), same-day entry/exit — explicitly **no options/derivatives, no small/micro-caps** (liquidity, circuit-filter, and MIS-eligibility risk)
- **TradingView**: excluded from the automated pipeline entirely — it has no official API, its Paper Trading is UI-only, and its MCP servers are unofficial scraping (ToS/ban risk). Optional manual chart-browsing only, never wired into execution.
- **SEBI compliance**: retail algo framework is fully in force since April 1, 2026. Static IP + OAuth + 2FA required only for live order-placement API access (Phase 3), not for backtesting/paper trading. A single retail bot stays far under the ~10 orders/second threshold that would trigger formal algo registration.

## Working preferences (how Ameen wants this worked on)

- Go phase by phase — don't jump ahead. Present decisions as short "option A vs option B" comparisons before locking each one in.
- Actually research claims rather than relying on general knowledge, especially for anything a backtest depends on (data granularity, library maintenance status, cost assumptions) — several early assumptions turned out wrong on verification (jugaad-data's granularity, backtrader's Python 3.13 risk) and would have silently broken the plan if not checked.
- Willing to build a custom strategy from scratch if the researched candidates don't pan out — they're starting points, not a final answer.
- Save plan/deliverable files as markdown **in the project working directory**, not only in chat or in Claude's default plan-file location.
- **Do not start installing/building/executing just because a plan was approved** — confirm explicitly before moving from "plan" to "action," even after approval. Ameen corrected this assumption once already in this project.

## Next step when resuming

Phase 1b validation is **complete**. All six pre-registered criteria pass, plus a permutation test and a Bonferroni correction. Every remaining question needs something a backtest cannot supply.

**Next is Phase 2 — paper trading forward.** It does two jobs at once:

1. It is the only genuinely out-of-sample test still available, because the holdout was observed before it was sealed (see `phase-1b` §6).
2. It measures **slippage**, currently the largest unverified assumption in the whole model. The cost model assumes 5 bps/leg; the current buy list contains names trading near ₹14 where that could be badly optimistic.

Mechanically it is light — no WebSocket, no intraday event loop. Run `live/generate_orders.py` on schedule, record what it says, and compare the next open's fills against `ref_price`.

Smaller open items: resolve `GUJGASLTD` and `LTIM` in the scrip-master lookup; verify `nifty200.json` against the live NSE constituent list; decide whether the compromised holdout is worth re-cutting.

Do not fund an account before paper trading has measured real slippage. The intraday phase looked convincing on 5 symbols and collapsed on 50 — that is the specific failure this sequence exists to prevent.

Ask before starting — don't assume approval of a plan is approval to execute it.
