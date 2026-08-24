# Next-day direction — a feasibility study

Can tomorrow's winners be picked from daily OHLCV — previous close, volume,
resistance — with a big win rate, an SL, a TP, and an estimate of how far each
name will move?

The question was tested before anything was built. 205 NSE symbols, 15 years of
daily bars, walk-forward and out of sample, with the last 24 months sealed.

> **Scope of this branch.** `intra-multi` carries only this study. The completed
> intraday work, the delivery/CNC momentum result and the paper-trading pipeline
> live on `main`.

---

## The short version

**Direction is predictable, but barely — and the signal points backwards from
where the question expected it.**

| question | answer |
|---|---|
| Can next-day direction be predicted? | Yes, weakly. OOS IC **+0.025**, top-5 beats the universe by **+11.7 bps/day** (t = 5.23), positive in **9 of 10** out-of-sample years. |
| Is it a trend/breakout signal? | **No — the opposite.** Every informative feature has a *negative* IC. |
| Can it say how far a stock moves? | **Size yes, direction no.** ATR predicts tomorrow's range at r = 0.49; the signed return at r = 0.018. |
| Can the win rate be big? | Yes, and it proves nothing. **80% is available on demand — random picks reach it too.** |

The practical finding is the holding period: at 1 day there is ~12 bps of edge
against a 27–104 bps round trip. **The signal is fine; one day is the wrong
horizon.**

That conclusion was then built and tested. **The screener cleared all six
pre-registered criteria on 13 years and failed to replicate on the sealed
holdout** — see [Built, gated, rejected](#built-gated-rejected). Nothing here is
fundable; what remains is a documented method and two transferable findings.

## Win rate is a dial, not an achievement

Same picks, same days. Only the barriers move:

| TP/SL (ATR) | model win % | **random win %** | model bps | payoff |
|---|---:|---:|---:|---:|
| 2.0 / 1.0 | 46.4 | 44.1 | +31.7 | 1.36 |
| 1.0 / 1.0 | 51.7 | 50.4 | +17.4 | 1.03 |
| 1.0 / 2.0 | 58.5 | 57.9 | +35.2 | 0.86 |
| 0.5 / 3.0 | **80.2** | **81.2** | +35.2 | 0.31 |

Widen the stop against the target and you win more often and lose more when you
lose. A "big win percent" target can be met exactly while making no money.
Expectancy is the `bps` column; the win column is geometry.

## The signal buys weakness, not strength

Every feature that carries information has a negative information coefficient —
distance above the 20-DMA (−0.027), 5-day return (−0.028), closing near the
20-day high (−0.016), RSI (−0.024), consecutive up days (−0.022).

Yesterday's strongest names underperform tomorrow. A screener that buys
breakouts is on the wrong side of the only effect present.

It is not a bid-ask artifact. Scored against a target sharing **no price** with
the features — close(D+1)→close(D+2) — reversal persists at −0.020 (t = −8.42).
About 20% of it is bounce; the rest is real.

## Rejected: the 71% overnight trade

The highest win rate in the data is overnight: **63.3%** for a random name,
rising to **71.5%** once ranked, at OOS IC 0.162, positive in 10 of 10 years.

It is the bid-ask spread being measured, not captured:

| leg | edge vs universe | t |
|---|---:|---:|
| overnight close(D)→open(D+1) | +20.9 bps | 20.05 |
| session open(D+1)→close(D+1) | −17.0 bps | −7.01 |
| **full day** | **+3.6 bps** | **1.39** |

**83% of it is handed back during the next session.** Sorted by volatility, the
overnight column rises (12.2 → 24.5 bps) while the session column falls almost
in step (−5.0 → −11.9): wider-spread names show a bigger fake gap and a bigger
fake fade. On the 50 symbols with 5-minute data the leg is +5.5 bps close-to-open
on daily bars but only **+2.7 bps at 52.2%** between the 15:25 and 09:20 prints —
the two prices you could actually transact at.

## Built, gated, rejected

The study's recommendation — a reversal screener held 10 days — was built
(`strategies/reversal.py`) and gated against six pre-registered criteria.

| | development (2011–2024) | sealed holdout (2024–2026) |
|---|---|---|
| edge per 10-day window | **+27.3 bps**, t = 2.29 | **+8.7 bps**, t = 0.94 |
| criteria cleared | **6 of 6** | 1 of 5 evaluable |
| book vs universe (CAGR) | **33.96%** vs 22.91% | 3.34% vs 1.16% |
| max drawdown | −35.53% vs −37.47% | −28.16% vs −21.38% |

**It did not replicate, and the window had the power to say so:** the holdout's
standard error is 9.2 bps, so a +27.3 bps edge would have printed t = 2.97 there.

What survived is the *sign*, not the size — the screener still beat 20 of 20
random seeds and the bottom of its ranking was still the worst bucket. The
likeliest reading is a weak real effect inflated in-sample by choosing the design
(horizon, components, pick count) on the window it was scored on.

Two findings outlived it:

- **Stops make a mean-reversion book worse, drawdown included.** Time exit only:
  33.96% CAGR at −35.5% max DD. A 2.0/3.0 ATR stop-and-target: 24.82% at −46.0%.
  A stop sells exactly what the signal bought and locks in the loss the trade
  existed to recover. SL/TP levels are risk context, not an exit rule.
- **Entry timing is worth ~3 points of CAGR** — buying into the close rather than
  the next open, on identical picks, because the overnight move is real even
  though it cannot be traded on its own.

## Horizon is what has to change

Same out-of-sample picks, held longer:

| hold | 1d | 2d | 5d | 10d | 20d | 40d |
|---|---:|---:|---:|---:|---:|---:|
| edge vs universe (bps) | +11.7 | +22.6 | +45.0 | +74.5 | **+132.7** | **+235.5** |
| t (non-overlapping) | 5.23 | 6.28 | 5.58 | 3.62 | 2.78 | 3.29 |

A round trip is paid once per trade, not once per day, so the total edge column
is what clears it.

**But most of that long-horizon strength is not reversal.** The model behind this
table includes a turnover (size) feature, and size dominates at 10+ days — while
being the factor most exposed to survivorship bias, since this universe is
today's index membership applied to history. Ranking *within* turnover bands so a
pick cannot be a size bet, the 20-day edge falls from +132.7 bps (t 2.78) to
**+34.7 bps (t 1.37)**, and reversal alone peaks at 3–10 days. That correction is
why the built strategy holds 10 days and excludes size, and it is measured in
`G6` of the gate.

Full detail in
[`Learning-T/phase-2-nextday-direction.md`](Learning-T/phase-2-nextday-direction.md).

---

## Layout

```
strategies/
  panel.py                     # the shared price panel: OHLCV, corporate-action
                               # repair, calendar hygiene. Strategy-agnostic.
  features.py                  # the feature library, shared by study and strategy
  reversal.py                  # the screener - REJECTED at the holdout; run it
                               # for a list and it says so before it says anything
backtest/
  costs.py                     # intraday / delivery / hybrid, calibrated against
                               # a real contract note to the paisa
  nextday/
    feasibility.py             # the study - run and read this first
    test_reversal.py           # the pre-registered gate, dev and holdout
  results/nextday/             # feasibility_report.txt + CSVs
    reversal/                  # gate on the development window (6 of 6)
    reversal_holdout/          # gate on the sealed window (1 of 5)
data/
  fetch_universe.py            # chunked fetcher (5-min and daily) + integrity audit
  fetch_historical.py
  corporate_actions.py         # detects and neutralises unadjusted splits
  nifty200.json / nifty50.json
  daily/                       # 205 symbols x 15 years
  intraday_5min/               # 50 symbols x 2 years
Learning-T/
  phase-0-setup.md             # accounts and environment
  phase-2-nextday-direction.md # this study, and what is worth building
```

## Running it

Requires **Python 3.13**. The virtualenv is deliberately not committed.

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
```

Everything reproduces from the committed data — no credentials, no network:

```bash
python backtest/nextday/feasibility.py                      # the study
python backtest/nextday/feasibility.py --universe intraday50
python backtest/nextday/test_reversal.py                    # the gate
python backtest/nextday/test_reversal.py --holdout          # the rejection
python strategies/reversal.py                               # today's list + SL/TP
python backtest/costs.py                                    # cost tables + contract-note check
python data/corporate_actions.py                            # what gets repaired, and why
```

The study seals the final 24 months by default; `--full-sample` includes them
and says so in the report header. Output lands in `backtest/results/nextday/`.

Refreshing the data needs Angel One credentials in `.env` (see `.env.example`):

```bash
python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15
```

Dependency versions are pinned — `pandas` 3.x and `numpy` 2.x both carry
behaviour changes that move the numbers.

---

## Methodology notes

- **Falsify the good result first.** The strongest finding in the study (71% win
  rate overnight) is the one that turned out to be an artifact. It was tested
  because it was strong, not despite it.
- **t-stats across dates, never across name-days.** Picks on the same date share
  that day's market move; pooling name-days inflates t by roughly √(names/day).
  Multi-day holds are reported on non-overlapping windows as well.
- **Measure against the benchmark, not zero.** A long-only equity strategy making
  money proves nothing — the market rises. Every edge here is a paired daily
  difference against equal-weighting the eligible universe.
- **Out of sample means out of sample.** The model is refit annually on an
  expanding window and scored only on the following year.
- **Controls before conclusions.** Randomized selection, a bid-ask-bounce control
  using targets that share no price with the features, and an independent check
  of the closing print against 5-minute traded prices.
- **Point-in-time features.** Row D uses only data through D's close.
- **Corporate actions repaired before ranking on trailing returns.** One
  unadjusted split fabricates an enormous fake signal.
- **Pre-sealed holdout.** The last 24 months are excluded by default and were
  not consulted.

## Caveats

Research code, not trading advice. Nothing here has been traded live or on paper.

Costs are excluded from this study by instruction, so every figure is an **upper
bound** on what is tradeable.

The universe carries **survivorship bias** that free data cannot remove — today's
index membership applied to historical data excludes companies that failed.
Returns are price-only (no dividends). Historical data under `data/` came from
Angel One SmartAPI and is **unadjusted** for corporate actions; see
`data/corporate_actions.py`.

A feasibility result is not a strategy. It establishes that a weak, real,
mean-reverting signal exists and that its usable horizon is longer than one day.
It does not establish that any particular set of rules built on it will make
money after costs.
