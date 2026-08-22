# Phase 2 — Local Paper Trading

> **REVISED for delivery/CNC — most of this phase just got much smaller.**
>
> This was written for intraday: a 9:15–3:30 event loop, simulated fills against
> a live tick feed, a WebSocket, and an intraday `paper_broker.py`. **None of
> that is needed for a monthly-rebalanced delivery strategy.**
>
> What Phase 2 actually is now:
> 1. Run `live/generate_orders.py` after the close on each rebalance date. It
>    already exists and shares `select()` with the backtest.
> 2. Record the orders it produces, and what they *would* have filled at the
>    next open.
> 3. Track the paper portfolio for a few rebalance cycles against the backtest's
>    expectation.
>
> **The one thing this phase must actually measure: real slippage.** The backtest
> assumes 5 bps/leg. `generate_orders.py` prints `ref_price` (the rebalance
> close); the gap between that and where you could actually have filled at the
> next open IS the slippage assumption being tested. That is the main open
> question the backtest cannot answer, and it is worth more than everything
> else in this phase.
>
> No `paper_broker.py`, no `engine/runner.py`, no WebSocket. The material below
> is kept for reference on broker choice and the no-static-IP reasoning, both of
> which still hold.

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
