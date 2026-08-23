# Hybrid Intraday-to-Delivery Momentum — rejected at the screener

A single result, on one branch: a proposed NSE strategy that screens daily, buys MIS at the open, converts winners to CNC at 15:00 and manages the delivery leg to +5% / −3%, on ₹5,000 of capital.

**It was tested and rejected before any execution engine was written.** The proposed ranking is significantly *anti*-predictive at a one-day horizon — it loses to picking stocks at random.

> **Scope of this branch.** `intra-multi` carries only this strategy. The completed intraday work, the delivery/CNC momentum result (+12.18%/yr over buy-and-hold) and the paper-trading pipeline live on `main`. Nothing here supersedes them — the cost-model correction below makes the intraday rejection there *wider*, not narrower.

---

## The result

Pre-registered criteria, scored on the development window with the 24-month holdout sealed:

| # | Criterion | Result | |
|---|---|---|---|
| G1 | Next-day open→close edge over the universe > 0, t > 2 | −6.2 bps, t = −2.55 | **FAIL** |
| G2 | Rank monotone: top-1 ≥ top-3 ≥ universe ≥ bottom-3 | bottom-3 (+9.8) beats top-3 (+8.6) and the universe (+7.8) | **FAIL** |
| G3 | Beats ≥ 19 of 20 random-selection seeds | 8/20 | **FAIL** |

G2 is the mirror test that validated the delivery momentum work on `main`. Here it fires backwards: the screener's *worst*-ranked names outperform its best.

Re-run on just the 50 symbols that have 5-minute data — the names the strategy could actually have traded — it fails harder: **G1 = −5.6 bps at t = −3.22, and G3 = 0 of 20 random seeds beaten.** Screening the full 205 while only 50 are tradeable would itself have been a selection bias, since only 15% of top-3 picks land in that 50; screening inside it removes the bias and the result gets worse.

## Why gate the screener instead of building the engine

The proposal said the screener was "the most critical step — the screener quality determines everything." That is correct, and it is why no engine exists.

**A screener built from daily bars can be scored on 15 years and 205 symbols without simulating a single intraday fill.** If the ranking carries no next-day information, no stop-loss placement or conversion rule can rescue it, and building the engine first is an expensive way to discover that. So the screener was gated first, against criteria written down before the run.

## Why the same-day leg cannot work

Decomposing the universe's own return answers it before any strategy is involved:

| Segment | bps/day | Hit rate | t |
|---|---:|---:|---:|
| Overnight (prev close → open) | **+18.4** | 75.3% | 17.7 |
| Intraday (open → close) | **−10.2** | 49.4% | −6.0 |
| Full day (close → close) | +7.8 | 59.0% | 4.2 |

Essentially all of the drift is delivered overnight and the continuous session is a net drag. **A design that buys at 09:15 and exits by 15:00 donates the first and pays the second**, before a single rupee of brokerage.

## Two of the six factors could not rank anything

The proposed score was six factors at 25/20/20/15/10/10. Two are arithmetically incapable of reordering a cross-section:

- **"Relative strength vs Nifty"** (20%) is the stock's 20-day ROC minus the index's. The index term is one number per date, identical for every symbol, and subtracting a per-date constant is rank-preserving. It was **rank-identical to plain 20-day ROC on 500 of 500 dates tested.** It survives only as a *regime filter*, comparing the index to its own moving average — which does do something.
- **"Above the 50-DMA"** (15%) was listed as both a hard filter and a weighted score. Once it is a filter, every surviving name scores identically.

The momentum leg was the deeper problem: a **20-day ROC with no skip** sits inside the short-term reversal window that cross-sectional momentum deliberately skips a month to avoid. Scored as specified, the screener is **−11.1 bps vs the universe on open→close (t = −4.18)** and **−6.2 bps on close→close (t = −2.23)**, underperforming equal-weighting at every holding period from 1 to 20 days.

Rebuilding it as a 60-day ROC skipping 5 days, with the two dead factors removed, is what G1–G3 above actually score. It still fails. Notably the corrected composite is **worse than its own best single factor** — momentum alone is +5.7 bps vs the universe at t = 2.03, the four-factor blend is +0.8 at t = 0.31 — which is what adding uninformative factors to a ranking does.

## The cost model was understated, and a real contract note fixed it

The legacy `brokerage_per_order()` charges ₹20 or 0.03% of turnover, whichever is lower. Angel One's actual 2026 intraday rate is the same `max(₹5, min(₹20, 0.1%))` schedule it uses for delivery. A real round trip supplied by the account holder:

| | Turnover | Charged | Legacy model |
|---|---:|---:|---:|
| Buy | ₹4,852 | ₹6.08 | — |
| Sell | ₹4,640 | ₹7.07 | — |
| **Round trip** | | **₹13.15 (27.1 bps)** | **₹5.01 (10.3 bps)** |

`intraday_leg_2026()` reproduces both legs **to the paisa** and is asserted against them in `python backtest/costs.py`. Two details only matter at this size: STT and stamp duty are billed in whole rupees, and the ₹5 brokerage floor binds below ₹5,000 of turnover. The legacy functions are kept untouched so the published numbers on `main` still reproduce.

**On ₹5,000, the DP charge dominates everything.** It is a flat ₹20 + GST = ₹23.60 per scrip per sell, confirmed against the account holder's own charges:

| Split | Each | MIS | Hybrid MIS→CNC | CNC | DP alone |
|---|---:|---:|---:|---:|---:|
| 1 position | ₹5,000 | 36.3 | **103.5** | 103.0 | 47.2 |
| 2 positions | ₹2,500 | 61.9 | 168.3 | 173.8 | 94.4 |
| 3 positions | ₹1,667 | 81.5 | **247.1** | 244.6 | 141.6 |

So the proposal's "+5% target, −3% stop, 1:1.67, needs a 38% win rate" is a statement about *prices*, not money. After costs it is **+3.96% / −4.03%, R:R 0.98, breakeven win rate 50.5%** on one position — and **71.5%** split three ways. Concentration is not a preference here; the flat DP charge makes splitting ₹5,000 structurally unaffordable.

Slippage is almost irrelevant at this size: moving it from 5 bps/leg to zero changes the hybrid round trip by 10 bps out of 104. **The cost is nearly all statutory and exactly known**, so "but slippage is only assumed" is not an available objection to this rejection.

## What survived, and what it isn't

One result passed. At a **40-day hold** the corrected screener beats the equal-weight universe by **+117 bps (t = 2.55, non-overlapping windows)**, and clears its own ₹5,000 round-trip cost at 20 and 40 days. Every shorter horizon is inside the noise:

| Hold | 1d | 3d | 5d | 10d | 20d | 40d |
|---|---:|---:|---:|---:|---:|---:|
| Edge vs universe (bps) | +0.8 | −5.0 | −8.9 | −0.8 | +7.9 | **+116.8** |
| t (non-overlapping) | 0.31 | −1.75 | −1.20 | −0.38 | 1.85 | **2.55** |

That is **not a reprieve for this strategy.** It is a different one: a multi-week position with no intraday leg, no MIS entry and no 15:00 conversion — none of which the gate tested. It is also close to what the delivery momentum work on `main` already trades and has validated, on a longer lookback and 20 names rather than 3. Treating it as a new finding would require a pre-registered head-to-head against that.

**What this establishes:** that the proposed ranking is anti-predictive at a one-day horizon, that two of its six factors could not have contributed, and that ₹5,000 of capital faces a 104 bps hybrid round trip which a +5% target cannot comfortably clear. **What it does not:** that trade management is irrelevant. Stop placement and the conversion rule change the *distribution* of outcomes, and daily bars cannot see intraday path dependence. The claim is narrower — that the selection those rules would act on does not beat random, which makes the question moot rather than answered.

---

## Layout

```
strategies/
  hybrid_momentum.py                 # screener, levels, controls (marked REJECTED)
backtest/
  costs.py                           # intraday, delivery, hybrid + the 2026 calibration
  hybrid_momentum/
    test_screener_gate.py            # the gate - run and read this first
  results/hybrid_momentum/           # gate_report.txt + 6 CSVs
data/
  fetch_universe.py                  # chunked fetcher (5-min and daily) with integrity audit
  fetch_historical.py
  corporate_actions.py               # detects and neutralises unadjusted splits/demergers
  nifty200.json / nifty50.json
  daily/                             # 205 symbols x 15 years
  intraday_5min/                     # 50 symbols x 2 years
Learning-T/
  phase-0-setup.md                   # accounts and environment
  phase-1c-hybrid-momentum.md        # the plan, with the outcome prepended
```

## Running it

Requires **Python 3.13**. The virtualenv is deliberately not committed — it hardcodes absolute paths to the machine that built it.

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
```

Everything reproduces from the committed data, with no credentials and no network:

```bash
python backtest/costs.py                                # cost tables + the contract-note check
python data/corporate_actions.py                        # what gets repaired, and why
python backtest/hybrid_momentum/test_screener_gate.py   # the gate, and why it failed
python backtest/hybrid_momentum/test_screener_gate.py --universe intraday50
```

The gate seals the 24-month holdout by default; `--full-sample` includes it and says so in the report header. It writes `gate_report.txt` plus the underlying CSVs to `backtest/results/hybrid_momentum/`.

Refreshing the data needs Angel One credentials in `.env` (see `.env.example`):

```bash
python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15
```

Dependency versions are pinned — `pandas` 3.x and `numpy` 2.x both carry behaviour changes that move the numbers.

---

## Methodology notes

- **Gate the signal before building the engine.** A daily-bar screener is cheap to falsify; an execution engine is not.
- **Measure against the benchmark, not against zero.** A long-only equity strategy making money proves nothing — the market rises. Every figure above is a paired daily difference against equal-weighting the eligible universe.
- **t-stats across dates, not name-days.** Picks on the same date share that day's market move, so pooling name-days inflates t badly. For multi-day holds the windows overlap, so a non-overlapping estimate is reported alongside.
- **Randomized controls and a mirror test**, built in from the start rather than bolted on.
- **Point-in-time filters.** Eligibility and every factor are computed only from data available at the signal date.
- **Corporate-action audit before ranking on trailing returns.** One unadjusted split fabricates an enormous fake signal.
- **Calendar hygiene.** Six dates where the cross-section collapses to a handful of symbols (Muhurat sessions, truncated feeds) are dropped; one falls inside the intraday window.
- **Known-answer tests.** The cost model is asserted against a real contract note, to the paisa.
- **Pre-registered kill criteria**, written before seeing results, and actually honoured — the engines in the original plan were never built.

## Caveats

Research code, not trading advice. Nothing here has been traded live or on paper.

The universe carries **survivorship bias** that free data cannot remove — today's index membership applied to historical data excludes companies that failed. Returns are price-only (no dividends). Historical data under `data/` was retrieved via Angel One SmartAPI and is **unadjusted** for corporate actions; see `data/corporate_actions.py`.

The rejection is a screening result, not an execution result. It establishes that the proposed ranking loses to random selection at a one-day horizon; it does not establish that stop placement and MIS→CNC conversion are worthless in general.
