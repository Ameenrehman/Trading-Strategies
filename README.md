# Trading-Strategies

Backtesting NSE intraday cash-equity strategies with a realistic Indian cost model — and measuring honestly enough to tell a real edge from a bookkeeping illusion.

Part of a staged project: **backtest → paper trade → live execution** via Angel One SmartAPI. Only Phase 1 (backtesting) is in this repo.

**Scope:** same-day cash equity, Nifty 50/100 large-caps. No options, no derivatives, no small-caps, no overnight positions.

---

## The core idea

Most retail intraday backtests fail in the same way: they report **total return**, size every trade at ~100% of equity, and then conclude that costs killed an otherwise good strategy.

That framing hides the actual question. With full-equity sizing, total return is roughly the per-trade edge compounded over the trade count — so a strategy trading 400×/year looks catastrophic and one trading 70×/year looks promising, purely because it paid the toll fewer times. **You end up ranking strategies by how little they trade.**

This repo measures **gross bps/trade → realised cost → net bps/trade**, with a t-stat and a multiple-testing correction. That single change reversed most of the conclusions from the first round of testing.

---

## Results so far

**11 strategies tested across 4 families**, 5 large-caps, 2 years of 5-minute bars (493 sessions), zero-cost runs to isolate the raw signal:

| Strategy | Family | Trades | Gross bps/trade | t |
|---|---|---:|---:|---:|
| Gap + ORB continuation | selectivity | 343 | **+7.67** | 1.95 |
| Trend Gap + EMA trail | selectivity | 560 | **+7.27** | 2.59 |
| NR7 / Inside-Bar | selectivity | 458 | **+5.04** | 1.92 |
| Prev-day High/Low | selectivity | 1677 | **+3.58** | 2.35 |
| VWAP breakout | VWAP | 1954 | +0.75 | 0.48 |
| Supertrend | trend | 1691 | +0.52 | 0.32 |
| Trend+Vol filtered ORB | ORB | 913 | -0.14 | -0.06 |
| Gap fade | mean-rev | 346 | -0.17 | -0.05 |
| Naive ORB 30m | ORB | 1942 | -0.88 | -0.48 |
| VWAP pullback | VWAP | 2114 | -2.05 | -1.60 |
| EMA momentum | trend | 1328 | -2.68 | -1.55 |

The ordering isn't random. **The top four all decide *which sessions to trade*** rather than trading every morning. Every ORB, VWAP, trend-following and mean-reversion variant sits at or below zero.

Naive ORB in particular has **no edge at all** — not "an edge destroyed by costs". Its headline -56% two-year return is entirely toll: 388 trades × ~20 bps.

### Round 2 — Dynamic Gap + RVOL Momentum

Trade only gapped sessions, enter in the gap direction at the opening-range extreme, hold with an ATR chandelier trailing stop, size by fixed-fractional risk.

Gross edge rises **monotonically** with the gap threshold — 6.9 → 9.4 → 16.5 → 18.1 → 27.9 bps as it goes 0.3% → 1.5%. That's a mechanism, not a parameter spike: cost is fixed per trade, so edge has to be measured against how much movement the setup offers.

Best variant (gap ≥1.0% + RVOL ≥1.5): **+30.7 bps gross, +15.8 bps net per trade.**

### The control test

Big-gap, high-RVOL days are also *volatile* days, and a trailing stop on a volatile day captures range regardless of direction. If that were the whole story, the edge is an artifact. Same days, same levels, same exits — only direction changes:

| Configuration | Trades | Gross bps | Net bps |
|---|---:|---:|---:|
| **Real — follow the gap** | 94 | **+30.66** | **+15.78** |
| Random direction (mean, 20 seeds) | ~88 | +8.50 | -6.15 |
| **Inverted — fade the gap** | 97 | **-10.95** | **-25.44** |

Real beats **20/20** random seeds, and the result is roughly symmetric around the random baseline (+22 above, −19 below). A volatility artifact would show real ≈ inverted ≈ random.

Honest split: random direction still earns +8.5 bps gross, so part of the raw edge really is volatility capture. Direction adds ~22 bps on top.

**Status: not validated.** 94 trades, best-of-10 selected in-sample, no out-of-sample test. **3 of 6 go/no-go criteria met.** The blocker is sample size, which is why the next step is widening from 5 symbols to 50.

---

## Cost model

NSE cash-equity intraday, 2026 tax year. **₹103.06 round-trip on a ₹50,000 position = 0.2061%.**

| Component | Rate | Side | Share |
|---|---|---|---:|
| Brokerage | ₹20 flat or 0.03%, lower of the two, per order | Both | 29.1% |
| STT | 0.025% | Sell only | 12.1% |
| Exchange charges | 0.003% | Both | 2.9% |
| SEBI turnover fee | 0.0001% | Both | 0.1% |
| Stamp duty | 0.003% | Buy only | 1.5% |
| GST | 18% on (brokerage + exchange + SEBI) | — | 5.8% |
| **Slippage** (estimate) | **0.05% per leg** | Both | **48.5%** |

Two details that matter:

- **Costs are charged per order, not as a flat fraction.** `angel_intraday_commission()` is passed as a callable to Backtesting.py's `commission`, so the ₹20 cap applies to each order's real turnover, STT hits only the sell leg, and stamp duty only the buy leg.
- **Slippage lives in `spread`, not `commission`.** Slippage moves the fill price; it isn't a fee.

**The hurdle is size-dependent.** 20.6 bps is the cost on a ₹50,000 position. At realistic risk-based sizes it measures 13–15 bps. Always report the realised figure.

---

## Layout

```
strategies/
  session.py             # session structure, day-aware ATR, risk sizing
  orb_strategy.py        # opening range breakout
  gap_rvol_strategy.py   # dynamic gap + RVOL momentum
backtest/
  costs.py               # Indian cost model + per-order commission callable
  verify_fixes.py        # invariant checks (no overnight leaks, RR, sizing)
  test_gap_rvol.py       # gap threshold / filter sweep
  test_gap_controls.py   # randomized- and inverted-direction controls
  validate.py            # overfitting suite (walk-forward, holdout, ...)
data/
  fetch_universe.py      # chunked 50-symbol fetcher + integrity audit
  nifty50.json           # universe list
Learning-T/              # planning docs, full methodology and findings
```

## Running it

Requires **Python 3.13**. The virtualenv is deliberately not committed — it hardcodes absolute paths to the machine that built it and won't run anywhere else.

```bash
git clone https://github.com/Ameenrehman/Trading-Strategies.git
cd Trading-Strategies

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # macOS / Linux

pip install -r requirements.txt
```

Then run any of these — **no API access or credentials needed**, the 5-symbol dataset is committed:

```bash
python backtest/verify_fixes.py       # invariant checks + before/after comparison
python backtest/test_gap_rvol.py      # the gap threshold sweep
python backtest/test_gap_controls.py  # the randomized-direction control test
python backtest/costs.py              # cost breakdown by position size
```

Dependency versions are pinned, because `pandas` 3.x and `numpy` 2.x both carry behaviour changes that can move the numbers.

Fetching **new** data does need Angel One SmartAPI credentials in `.env` (see `.env.example`):

```bash
python data/fetch_universe.py --symbols TCS,INFY   # try two names first
python data/fetch_universe.py                      # full Nifty 50, ~6 min
python data/fetch_universe.py --audit-only         # integrity check, no network
```

---

## Methodology notes

Things this repo tries to do properly, because the first round got them wrong:

- **Fixed-fractional risk sizing**, not ~100% of equity per trade, so results are comparable in R-multiples.
- **Timestamp-keyed sessions**, not bar counts — a missing bar shouldn't shift the opening range.
- **Day-aware ATR** — the overnight gap is not intraday range.
- **Verified no overnight leakage.** An earlier version silently held 4 positions overnight on days with a truncated feed.
- **Entries as resting stop orders at the breakout level**, not market fills at the close of whichever bar broke it.
- **Corporate-action audit before backtesting.** One unadjusted split fabricates an enormous fake signal for a gap strategy.
- **Multiple-testing correction.** Every variant tested raises the bar; the count is tracked and reported.
- **An untouched out-of-sample holdout**, reserved for exactly one test at the end.

## Caveats

Research code, not trading advice. Nothing here has been paper-traded or traded live, and no strategy has passed validation. Backtested edges routinely fail to survive real execution — slippage on a momentum entry is plausibly worse than the 5 bps/leg assumed here, and measuring it for real is a Phase 2 deliverable.

Historical data included under `data/` was retrieved via Angel One SmartAPI and is provided for reproducibility of these results.
