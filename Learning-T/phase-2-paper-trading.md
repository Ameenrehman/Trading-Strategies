# Phase 2 — Local Paper Trading

Goal: forward-test the strategy from Phase 1 against real live prices, with simulated fills, on your own PC — no real orders, no static IP needed.

## Decisions (already locked, listed here for reference)

### Broker — Angel One vs Dhan vs Upstox vs Zerodha
- **Angel One (chosen)**: free, official SDK, **no paper-trading sandbox** — "paper trading" means a self-built simulated broker
- Fallback: **Dhan** — also free, and has a real broker-side paper-trading sandbox (mock fills, daily reset); switch here first if you'd rather skip building `paper_broker.py` yourself
- Fallback: **Upstox** — free API but ~₹10/live order (verify current pricing), has sandbox
- Fallback: **Zerodha** — best docs/community, but ₹500/mo for market data

## Why no static IP is needed here

Paper trading only *reads* market data (LTP/quotes) — it never calls the live order-placement endpoint. SEBI's static-IP/2FA rules apply specifically to order-placement API access, so none of that applies during this phase.

## Tasks

- [ ] Build `paper_broker.py`: same method signatures as a real broker (`place_order`, `get_positions`, `get_pnl`) but fills are simulated against live LTP/quotes pulled read-only from Angel One's market-data API
- [ ] Run `engine/runner.py` during market hours (9:15–3:30 IST) driven by the same strategy classes from Phase 1, now event-driven instead of vectorized
- [ ] Log every simulated trade to a local SQLite ledger
- [ ] Compare simulated performance against the Phase 1 backtest to catch look-ahead bias or over-optimistic slippage assumptions
- [ ] Run this for a meaningful stretch (weeks, not days) before considering Phase 3

## Verification

- Run `python main.py --mode paper` live during market hours, tail the SQLite ledger, confirm simulated fills track real quoted prices sensibly and match the strategy's backtested behavior.
