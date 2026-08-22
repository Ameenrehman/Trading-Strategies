# Phase 4 — Hardening (ongoing)

> **REVISED for delivery/CNC — most of this phase is no longer needed.**
>
> This was written to keep an always-on intraday bot alive: systemd service,
> WebSocket reconnect/backoff, "flat on disconnect". A monthly delivery strategy
> needs almost none of it.
>
> What remains:
> - A **monthly cron** (not a systemd service) that runs the signal job after
>   the close on rebalance dates.
> - `pandas_market_calendars` (`XNSE`) to identify the real last trading day of
>   each month — still needed, and now more important, since the whole schedule
>   hangs off it.
> - Alerting if the job fails to run — a missed rebalance is the main
>   operational risk, and it is silent.
> - Data freshness checks before acting on a signal. `generate_orders.py`
>   already warns if the data is more than 5 days old.
>
> What is gone: reconnect logic, disconnect handling, always-on uptime, and the
> intraday latency concerns.

Goal: keep the live bot running unattended and reliably, and only scale up once it's earned it.

## Tasks

- [ ] Wrap `engine/runner.py` as a systemd service on the EC2 instance (auto-restart on crash)
- [ ] Use `pandas_market_calendars` (`XNSE`) to skip NSE holidays automatically
- [ ] Add reconnect/backoff logic around the WebSocket feed and a "flat on disconnect" safety rule
- [ ] Only scale capital/position size after a sustained, consistent live track record
