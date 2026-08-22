# Trading-Strategies

Systematic NSE equity strategies tested against a realistic Indian cost model — and measured honestly enough to tell a real edge from a bookkeeping illusion.

Two parts, in order:

1. **Intraday** — 12 strategies, tested, **rejected**. A genuine edge was found and shown to be smaller than its own trading costs.
2. **Delivery / CNC momentum** — the current work. Built and validated; awaiting real data.

**Scope:** long-only NSE cash equity. No options, no derivatives, no small-caps.

---

## The core idea

Most retail backtests fail the same way: they report **total return**, size every trade at ~100% of equity, and conclude that costs killed an otherwise good strategy.

That hides the actual question. With full-equity sizing, total return is roughly the per-trade edge compounded over the trade count — so a strategy trading 400×/year looks catastrophic and one trading 70×/year looks promising, purely because it paid the toll fewer times. **You end up ranking strategies by how little they trade.**

This repo measures **gross edge → realised cost → net edge**, with t-stats, multiple-testing correction, and randomized controls. That change reversed most of the original conclusions.

---

# Part 1 — Intraday (complete, rejected)

11 strategies across 4 families, 5 large-caps, 2 years of 5-minute bars, zero-cost runs to isolate the raw signal:

| Strategy | Family | Trades | Gross bps/trade | t |
|---|---|---:|---:|---:|
| Gap + ORB continuation | selectivity | 343 | **+7.67** | 1.95 |
| Trend Gap + EMA trail | selectivity | 560 | **+7.27** | 2.59 |
| NR7 / Inside-Bar | selectivity | 458 | **+5.04** | 1.92 |
| Prev-day High/Low | selectivity | 1677 | **+3.58** | 2.35 |
| VWAP breakout | VWAP | 1954 | +0.75 | 0.48 |
| Supertrend | trend | 1691 | +0.52 | 0.32 |
| Naive ORB 30m | ORB | 1942 | -0.88 | -0.48 |
| EMA momentum | trend | 1328 | -2.68 | -1.55 |

The ordering isn't random: the top four all decide *which sessions to trade*. Every ORB, VWAP, trend and mean-reversion variant sits at or below zero. Naive ORB has **no edge at all** — its headline −56% two-year return is entirely toll.

The best variant (gap ≥1% + RVOL filter + ATR trailing stop) reached **+30.7 bps gross / +15.8 bps net** on 5 symbols and beat **20/20** randomized-direction control seeds, with the inverted variant symmetrically negative. That ruled out "it's just volatility capture."

**Then it was tested on 50 symbols and collapsed:**

| Group | Trades | Gross bps | Net bps |
|---|---:|---:|---:|
| Original 5 symbols | 94 | +30.66 | **+15.78** |
| The other 45 | 608 | +8.26 | **−6.47** (t = −2.15) |
| **All 50** | **702** | **+11.26** (t = 4.00) | **−3.49** |

The 5 development names were a favourable draw. On the 45 never used to build the strategy, net edge is significantly **negative**.

**Verdict: no go.** The edge is real (+11.26 bps, t = 4.00) and simply smaller than the ~14 bps it costs to trade. Breakeven needs 0.49 bps/leg slippage — effectively zero market impact. The pre-registered kill criterion fired and no live money was risked.

The binding constraint: **the same-day exit**. Median daily range is 142–192 bps, so each intraday round trip burns 8–10% of the entire day's available movement.

---

# Part 2 — Delivery / CNC momentum (current)

Holding longer attacks that constraint directly, because moves scale with roughly √time while cost is paid once:

| Hold | Median move | Delivery cost as % of move |
|---:|---:|---:|
| 1 day | 82 bps | 47.4% |
| 20 days | 418 bps | 11.1% |
| ~70 days | ~800 bps | **~6%** |

**But delivery costs 2.1× intraday**, because STT is 0.1% on *both* legs instead of 0.025% sell-only. Short 2–5 day swings are the worst of both worlds. The viable zone is multi-week holds — systematic momentum investing, not trading.

**Strategy:** 12-1 cross-sectional momentum (trailing 12-month return, skipping the most recent month to avoid short-term reversal), filtered to names above their 200-DMA, top 20 equal-weighted, monthly rebalance.

**Exits:** no stop-loss, no take-profit. The rebalance *is* the exit — a name is sold when it drops out of the top 20 or falls below its 200-DMA. Winners are allowed to run, which is where momentum's return comes from, and the 200-DMA filter is the systematic stop. Hard stops, daily trend exits and rank buffers are implemented as *testable options* rather than assumptions.

**Status:** built, 14/14 sanity checks passing on synthetic data with known answers. **No real-data result yet** — the daily fetch is blocked by a corporate firewall and runs on a personal machine.

### Rebalance frequency is not the same thing as turnover

Turnover is what costs money. Measured on the test framework:

| Schedule | Turnover/yr | Cost/yr |
|---|---:|---:|
| Monthly + rank buffer | 216% | **1.32%** |
| Monthly | 364% | 2.04% |
| Weekly + rank buffer | 338% | 2.10% |
| Daily + rank buffer | 527% | 3.03% |
| **Daily, no buffer** | **2,161%** | **9.52%** |

Naive daily rebalancing costs more than the entire expected premium, because names oscillate across the top-N boundary. A rank buffer — hold until a name drops out of the top (N + buffer) — fixes that far more cheaply than a slower calendar does.

### Pre-registered go/no-go

1. Beats equal-weight buy-and-hold by **≥3%/yr CAGR after costs**
2. Higher Sharpe, max drawdown no worse
3. Beats ≥19 of 20 random-selection seeds
4. Bottom-decile control clearly worse
5. Survives walk-forward without re-fitting
6. Holds up in the recent-5-year subsample

The 3% margin isn't arbitrary: applying today's index membership to years of history excludes companies that failed, and that bias is plausibly worth ~2%/yr.

**Kill criterion:** if it can't beat buy-and-hold by 3%/yr after costs, stop. An index fund is then the right answer.

---

## Cost model

`backtest/costs.py`. Both models are kept — conflating them is an easy way to build a strategy that looks profitable and isn't.

| Component | Delivery (CNC) | Intraday (MIS) |
|---|---|---|
| Brokerage | `max(₹5, min(₹20, 0.1%))` per order | `min(₹20, 0.03%)` per order |
| **STT** | **0.1% BOTH legs** | 0.025% sell only |
| Exchange txn | 0.00297% both | 0.00297% both |
| SEBI | 0.0001% both | 0.0001% both |
| Stamp duty | 0.015% buy only | 0.003% buy only |
| GST | 18% on (brokerage + exchange + SEBI + DP) | 18% on (brokerage + exchange + SEBI) |
| **DP charges** | **₹20 per scrip on sell** | none |

Round-trip on ₹1,00,000 at 5 bps/leg slippage: **intraday 18.3 bps, delivery 39.3 bps.** STT alone is 20 bps of the delivery figure — 50.9% — and being purely proportional it never amortises with size.

**The hurdle is size-dependent.** Below ~₹5L of capital, fixed ₹20 brokerage and ₹20 DP per scrip push annual drag above 2%.

---

## Layout

```
strategies/
  momentum_xs.py         # cross-sectional momentum + trend filter (current)
  session.py             # session structure, day-aware ATR, risk sizing (intraday)
  orb_strategy.py        # opening range breakout (rejected)
  gap_rvol_strategy.py   # gap + RVOL momentum (rejected)
backtest/
  costs.py               # intraday AND delivery cost models
  portfolio.py           # monthly-rebalance portfolio backtester
  test_portfolio_sanity.py   # 14 known-answer checks — run this first
  test_momentum.py           # momentum vs benchmark
  test_momentum_controls.py  # random-selection and bottom-decile controls
  verify_fixes.py            # intraday invariant checks
  test_gap_rvol.py / test_gap_controls.py   # intraday (rejected)
live/
  generate_orders.py     # the actual buy/sell list, sharing the backtest's signal code
data/
  fetch_universe.py      # chunked fetcher (5-min and daily) with integrity audit
  nifty200.json          # delivery universe
Learning-T/              # planning docs, methodology, full findings
```

## Running it

Requires **Python 3.13**. The virtualenv is deliberately not committed — it hardcodes absolute paths to the machine that built it.

```bash
git clone https://github.com/Ameenrehman/Trading-Strategies.git
cd Trading-Strategies

python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # macOS / Linux

pip install -r requirements.txt
```

Intraday results reproduce immediately — the 5-minute dataset is committed, no credentials needed:

```bash
python backtest/costs.py               # cost tables, both products
python backtest/verify_fixes.py        # intraday invariant checks
python backtest/test_gap_rvol.py       # the gap sweep
python backtest/test_gap_controls.py   # the control that killed it
```

The momentum work needs daily data, which requires Angel One credentials in `.env` (see `.env.example`):

```bash
python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15
python backtest/test_portfolio_sanity.py    # 14/14 before trusting anything
python backtest/test_momentum.py
python backtest/test_momentum_controls.py
```

Dependency versions are pinned — `pandas` 3.x and `numpy` 2.x both carry behaviour changes that move the numbers.

---

## Methodology notes

Things this repo tries to do properly, mostly because earlier versions got them wrong:

- **Measure gross edge, realised cost and net edge separately.** Total return conflates edge with trade frequency.
- **Fixed-fractional risk sizing**, not ~100% of equity per trade.
- **Randomized controls.** The intraday phase was decided by a randomized-direction test; the momentum phase has random-selection and bottom-decile controls built in from the start.
- **Multiple-testing correction.** Every variant tested raises the bar; the count is tracked and reported.
- **Point-in-time filters.** Eligibility is computed only from data available at each rebalance date.
- **Known-answer tests.** The portfolio backtester is verified against synthetic data where the correct result is known by construction — that caught three real defects before any market data was involved.
- **Corporate-action audit before backtesting.** One unadjusted split fabricates an enormous fake signal, especially for momentum, which ranks on trailing returns.
- **Pre-registered kill criteria**, written before seeing results, and actually honoured.

## Caveats

Research code, not trading advice. Nothing here has been paper-traded or traded live, and no strategy has passed validation. The momentum work carries **survivorship bias** that free data cannot fully remove — today's index membership applied to historical data excludes companies that failed, which inflates backtested momentum returns. Returns are price-only (no dividends).

Backtested edges routinely fail in live execution: slippage on a momentum entry is plausibly worse than the 5 bps/leg assumed here, and measuring it for real is an open task.

Historical data under `data/` was retrieved via Angel One SmartAPI and is included for reproducibility.
