# Handoff — NSE Automated Intraday Trading Bot

Read this first if you're picking this project up in a fresh conversation with no prior context.

## What this is

Ameen is building an automated intraday trading system for the Indian stock market (NSE): Python-based strategy backtesting → local simulated paper trading → live automatic order execution via a real broker (Angel One). Free tools only, runs locally where possible. Cash-equity intraday only — same-day entry/exit, no options/derivatives, no small-caps.

## Current status (as of 2026-08-22)

- **Phase 0** — done. SmartAPI auth + TOTP working, venv running.
- **Phase 1 (intraday) — COMPLETE AND REJECTED.** 12 strategies, 4 families, 50 Nifty stocks, 2 years of clean 5-minute data. A genuine directional edge was found (+11.26 bps gross, t = 4.00 over 702 trades, beating 20/20 randomized-direction controls) and shown to be **smaller than the ~14 bps it costs to trade**. Breakeven needed 0.49 bps/leg slippage. The pre-registered kill criterion fired. No money was risked.
- **Phase 1b (delivery/CNC momentum) — CURRENT.** Cost model, portfolio backtester, strategy, controls and order generation are all built and pass 14/14 known-answer sanity checks. **No real-data result yet** — blocked on the daily fetch.
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

Phase 1 is implemented but has **not** produced a validated strategy. The immediate work is listed in `phase-1-backtesting.md` §10 "Next", in order:

1. Fix the 8 implementation defects in §2 (position sizing, the dead stop-loss branch, and breakout-level entry are the three that change results).
2. Expand the data fetcher from 5 symbols to ~50 Nifty 50 names, with rate-limit backoff.
3. Build the morning gap/RVOL screener and the Dynamic Gap + RVOL Momentum strategy.
4. Test whether §4's gap-size finding survives on the widened universe. That is the make-or-break experiment for the whole project.

Ask before starting — don't assume approval of the plan is approval to execute it.

Also worth surfacing to Ameen: §9 defines an explicit kill criterion. If the widened-universe test doesn't clear ~25 bps gross edge, the honest conclusion is that retail-cost intraday cash-equity breakout trading on Nifty large-caps doesn't work, and stopping is a legitimate outcome.
