# Phase 0 — Accounts & Environment

Goal: get every account and local tool in place before writing strategy code. No regulatory constraints apply here — nothing in this phase places or even reads live orders.

**Updated after Phase 1 research**: Angel One's SmartAPI is now the primary historical data source for backtesting (jugaad-data turned out to be EOD-only, can't feed an intraday backtest — see `phase-1-backtesting.md`). That moves the SmartAPI registration from a "needed eventually" item to a **hard blocker for Phase 1**, not just Phases 2–3.

## Prerequisites

### Accounts
- **Angel One trading + demat account**, KYC completed and active (use an existing account, or open one — free, a few days for KYC approval if starting from scratch).
- **SmartAPI registration** at smartapi.angelbroking.com using your Angel One client code: generate an API key and enable TOTP-based 2FA (scan the QR into an authenticator app, or store the secret for `pyotp` to generate codes programmatically). **Needed starting Phase 1** — it's the historical intraday data source, not just for live orders later.
- **AWS account** with a payment method on file — only needed once you reach Phase 3 (EC2 + Elastic IP), not before.
- *(Optional, Phase 3)* a **Telegram bot token** (via @BotFather, free, ~2 minutes) if you want live/error alerts on your phone.

### Local machine
- **Python 3.13.7** (your current install) should be fine now — `backtrader`, the library with the Python 3.13 compatibility question, was ruled out; `Backtesting.py` (the chosen engine) is actively maintained with releases through Jul 2026. Still worth a quick install smoke-test rather than assuming.
- Ability to create a Python virtual environment and `pip install` packages (no admin rights required for either).
- Basic comfort reading/editing Python.

### Python dependencies to install (Phase 1 scope)
- `smartapi-python` — official Angel One SDK, used here for historical candle data (order placement comes later, Phase 3)
- `pyotp` — generates TOTP codes for SmartAPI login
- `backtesting` — the `Backtesting.py` package (pip name is `backtesting`)
- `pandas` — data handling
- `jugaad-data` — secondary use only: EOD/corporate-action validation, not the core intraday backtest
- `yfinance` — secondary use only: quick sanity cross-checks (60-day intraday cap)
- `python-dotenv` — load API keys/secrets from `.env` without hardcoding them
- `pandas_market_calendars` — NSE holiday calendar (`XNSE`), useful once building the historical data puller so it skips non-trading days automatically

### Knowledge / capital
- Enough margin in your Angel One trading account to place at least a handful of NSE intraday trades once you reach Phase 3 — sized to whatever you're comfortable risking; the bot itself starts at 1-quantity position sizing regardless of account size.
- No algo-trading certification or SEBI registration is required for personal use at this scale.

## Tasks

- [ ] Confirm/open Angel One account, complete KYC if needed
- [ ] Register at smartapi.angelbroking.com, generate API key, enable TOTP 2FA
- [ ] Create local Python virtual environment (`python -m venv .venv`)
- [ ] Install the Phase 1 dependency list above; smoke-test each import
- [ ] Create `infra/.env.example` with placeholders for API key / client code / TOTP secret (never commit real secrets)
- [ ] **Smoke-test an actual SmartAPI login + one historical candle pull** (e.g. a few days of 5-min bars for one Nifty 50 stock) — confirms the TOTP login flow and historical-data endpoint both work before building the real data pipeline on top of it
