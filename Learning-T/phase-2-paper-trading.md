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
> No `engine/runner.py`, no WebSocket. The material below is kept for reference
> on broker choice and the no-static-IP reasoning, both of which still hold.

---

## Correction — this phase cannot measure slippage, and does not need to

Phase 2 was scoped around one goal: measure the 5 bps/leg slippage assumption.
That goal was not achievable as stated, and the reason is worth recording.

The quantity being measured is the gap between `ref_price` (the rebalance close)
and the next morning's fill. Measured across 1,740 historical legs by
`backtest/test_execution_gap.py`, that gap has a **standard deviation of 112 bps
per leg**. A monthly rebalance produces ~20 legs, so:

| Paper trading | Legs | Standard error |
|---|---:|---:|
| 1 rebalance | 20 | ±25 bps |
| 6 months | 120 | ±10 bps |
| 1 year | 240 | ±7 bps |
| to reach ±2 bps | 3,141 | ~13 years |

A year of paper trading cannot distinguish 5 bps from 0 bps from 15 bps. The
measurement was never going to work, and running it for six months and reading
the mean as a result would have been worse than not running it — a confident
number with no power behind it.

### What the history says instead

The same daily bars already on disk answer the question directly, at every
month-end rebalance from 2011 to 2026:

| Leg | n | Mean | t |
|---|---:|---:|---:|
| Buys, raw | 880 | **+30.2 bps** | +8.05 |
| Sells, raw | 860 | **−29.3 bps** | −8.14 |
| **Net, both legs** | 1,740 | **+0.8 bps** | +0.31 |
| Universe-wide drift | 180 rebals | +24.9 bps | +5.53 |
| **Momentum excess over universe** | 880 | **+4.5 bps** | +1.44 |

Buys gapping up by 30 bps looks alarming until the control runs: the whole
universe gaps up +24.9 bps overnight, and the sells executed the same morning
recover it. The momentum-*specific* component is +4.5 bps, not distinguishable
from zero and almost exactly the 5 bps the backtest assumed.

**The cost model is conservative.** Nothing in this phase should be waited on
before trusting it.

### The look-ahead this nearly hid

The first implementation filled at whatever `ltpData` returned for `open`, which
is the *current* day's open. Run on the evening the orders were generated — the
natural thing to do — it filled at an open that preceded the close the signal
came from. On the 2026-08-21 order list that measured **−5.3 bps** of slippage:
a clean pass, reported as fills better than reference, i.e. free money.

`paper_broker.check_fill_timing()` now refuses any fill dated on or before the
signal date. Two more defects in the same area are written up in the ledger of
fixes below.

### What Phase 2 IS for

1. **Pipeline rehearsal.** Fetch, rank, order, fill, mark to market, without
   money involved. Bugs here are cheap; the same bugs in Phase 3 are not.
2. **Forward out-of-sample record.** The 24-month holdout was observed during
   the first real-data run. Forward time is the only clean out-of-sample left,
   and it only accrues by waiting.
3. **Market impact** — the difference between the printed open and *your* fill.
   That is the one execution cost history genuinely cannot show, and the one
   that needs real orders. Watch it in the thinnest names: the current book
   holds IDEA at ₹13.94, ~3,600 shares.

Judge Phase 2 on 1 and 3. Do not judge it on the slippage mean.

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

---

## Defects found reviewing the first Phase 2 implementation

Five, found by running the code rather than reading it. Three would have
corrupted results silently; the tests that shipped alongside passed throughout,
because each tested a function in isolation and every one of these lives in the
seams between functions.

### 1. Fill timing — look-ahead (critical)

`ltpData` returns the *current* day's open. Run the same evening the orders were
generated, the broker filled at an open six hours older than the signal.
Measured −5.3 bps on the live order list — reported as a pass.

Fixed: `check_fill_timing()` refuses to fill unless `fill_date > signal_date`,
and the ledger now records `signal_date`, `fill_date` and the source of every
quote.

### 2. Two schemas for one state file

`generate_orders.py` wrote `{as_of, capital, holdings}`. `paper_broker.py` wrote
`{as_of, capital, cash, holdings}`. Both directions broke:

- broker reading a generator file found no `cash` key, fell back to `capital`,
  and granted itself a fresh ₹10,00,000 of buying power on an already-invested
  book;
- generator reading a broker file ignored `cash` and hardcoded `0.0` whenever
  holdings existed, so every rupee released by a sell was stranded. At 516%/yr
  turnover the book bleeds into dead cash a little more each rebalance.

Verified live: with ₹8,298.81 of broker cash on disk, the generator printed
`Cash: Rs.0`.

Fixed: `live/portfolio_state.py` is now the single definition, imported by all
three scripts. It is deliberately free of network imports so `generate_orders.py`
still runs with no credentials and no SmartApi package.

### 3. Naked sells

The broker credited proceeds for the full ordered quantity without checking the
position. Selling 50 while holding 30 booked ₹24,926 of proceeds — ~₹10,000 of
money that never existed.

Fixed: quantity is clamped to holdings, with a warning.

### 4. Tracker crashed on an empty book

`compute_mark_to_market()` returned `{}` for an empty portfolio; the caller then
did `holdings_df.empty` on a dict. `AttributeError` on the very first run,
before any trade.

Fixed, and the empty case now prints the two commands that start the book.

### 5. The advertised benchmark did not exist

`track_performance.py` documented "tracks against: 1. Equal-Weight Buy & Hold
Benchmark" and computed no benchmark anywhere. That is the comparison the entire
Phase 1b case rests on — criterion 1 is beating buy-and-hold by ≥3%/yr — and
without it a positive P&L means nothing, because the market rises.

Fixed: NAV is now shown against equal-weight buy-and-hold over the identical
window, annualised and checked against the 3%/yr bar once there is a year of
history.

### Regression coverage

The NAV reconstruction in `dashboard.py` is checked against a known answer: a
12-month ledger replayed from the real strategy rebuilds to within ₹0.07 of the
independently-computed book value.

---

## Looking at it

```bash
python live/dashboard.py --open
```

Writes `live/dashboard.html` — one self-contained file, no server, no CDN, no
network. NAV against buy-and-hold on the same axes, holdings, and the execution
audit.

The HTML itself is gitignored — it is generated output and would churn on every
render. `positions.json` and `paper_ledger.csv` **are** committed while the book
is simulated: it is a virtual ₹10,00,000 with no broker account behind it, and
keeping the ledger in git history makes the forward out-of-sample record
timestamped and tamper-evident. That record is the only clean out-of-sample left
after the holdout was observed, so it is worth more in the repo than out of it.

**Both must be re-ignored before Phase 3.** The moment real orders are placed
they describe an actual portfolio and its size, on a public repository. The
marker is in `.gitignore`.

The page states plainly when a ledger contains simulated fills, and when the
elapsed window is too short to mean anything. A dashboard that reports a
number without its uncertainty is how a −5.3 bps look-ahead gets read as a pass.
