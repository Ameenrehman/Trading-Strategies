# Phase 4 — Hardening (ongoing)

Goal: keep the live bot running unattended and reliably, and only scale up once it's earned it.

## Tasks

- [ ] Wrap `engine/runner.py` as a systemd service on the EC2 instance (auto-restart on crash)
- [ ] Use `pandas_market_calendars` (`XNSE`) to skip NSE holidays automatically
- [ ] Add reconnect/backoff logic around the WebSocket feed and a "flat on disconnect" safety rule
- [ ] Only scale capital/position size after a sustained, consistent live track record
