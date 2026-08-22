# Phase 3 — Going Live

Goal: swap simulated fills for real orders, only after Phase 2 results hold up over a meaningful stretch. This is the phase where SEBI's order-API rules (static IP, OAuth, 2FA) actually apply.

## Decisions (already locked, listed here for reference)

### Bridge — custom build vs self-host OpenAlgo
- **Custom-built `paper_broker.py`/`live_broker.py` (chosen)**: full control, you understand every line that can place a real order, slower to build
- Fallback: **OpenAlgo** — actively maintained open-source India-specific platform with Angel One/Dhan/Zerodha plugins and TradingView-webhook ingestion already built; self-host instead if the custom build stalls. Lightweight enough for a 1 vCPU/1–2GB RAM box.

### Live hosting — AWS EC2 vs Oracle Cloud vs local PC + static IP
- **AWS EC2 (chosen)**: free-tier eligible `t2.micro`/`t3.micro`, `ap-south-1` (Mumbai) region for low latency, + an Elastic IP (free while attached to a running instance)
- Fallback: **Oracle Cloud free tier** — also has an always-free compute shape with a public IP
- Fallback: **Local PC + ISP static-IP add-on** — no cloud account needed, but depends on your PC/power/internet staying up during market hours

## Tasks

- [ ] Swap `paper_broker.py` for `live_broker.py` behind the same interface — real `placeOrder`/`modifyOrder`/`cancelOrder` calls via SmartAPI
- [ ] Launch EC2 instance in `ap-south-1`, allocate + attach an Elastic IP, whitelist it with Angel One
- [ ] Confirm OAuth + TOTP 2FA login flow; automate the daily TOTP re-auth (sessions are force-expired daily)
- [ ] Start with minimum position size (1 quantity)
- [ ] Add a hard-coded daily max-loss circuit breaker
- [ ] Add Telegram/log alerting on every order and error
- [ ] Confirm you stay far under the ~10 orders/second exchange threshold (trivial for a single retail bot) so no formal algo registration is triggered

## Verification

- Confirm Angel One's API dashboard shows the whitelisted static IP active.
- Place a single manual test order for 1 share before letting the bot run unattended.
- Monitor the first several live sessions closely.

## Guardrails / open risk items

- Angel One's published API rate limits have reportedly shifted over time and aren't perfectly reliable in practice — build retry/backoff regardless.
- WebSocket disconnects are a known Angel One SmartAPI complaint — treat a dropped feed as "stop opening new positions," not "assume nothing changed."
- Broker-side MIS (intraday) auto square-off happens before 3:30 PM and varies by broker — the bot must proactively flatten positions before that, not rely on the broker's own risk system as the exit plan.
