# Phase 2 — Next-day direction: feasibility

## The ask

> "Predict which of the top stocks will go up or down tomorrow, from previous
> close / volume / resistance. Give me a list to buy for next day with SL and TP,
> and how far it will move. Win percent should be big."

Feasibility was tested first, before building anything. The study is
`backtest/nextday/feasibility.py`; it reproduces every number below from the
committed data with no network and no credentials.

**Scope note.** Costs are excluded throughout, as instructed. Every figure here
is therefore an upper bound on what is tradeable. The last 24 months are sealed
as a holdout and were not looked at.

---

## The four answers

The request bundles four claims. They do not have the same answer, and the whole
risk of this project is letting a strong answer on one carry the other three.

### 1. Can next-day direction be predicted? Weakly — but genuinely.

Walk-forward, refit annually, scored only on the following year:

| | OOS IC | IC t | top-5 edge vs universe | t | hit rate | base rate |
|---|---:|---:|---:|---:|---:|---:|
| Buy at close(D), sell close(D+1) | +0.0248 | 9.40 | **+11.7 bps/day** | 5.23 | 51.6% | 50.5% |
| Buy at open(D+1), sell close(D+1) | +0.0495 | 19.61 | +11.8 bps/day | 6.65 | 48.1% | 45.2% |

Positive in **9 of 10** out-of-sample years. An IC near 0.025 is what a real
daily-bar equity signal looks like — small, and worth something only when it is
applied consistently across many names.

The honest translation of "+11.7 bps at 51.6%": the win rate improves by about
**one percentage point** over buying at random. That is the ceiling on "big win
percent" for a directional daily-bar call, and no amount of feature engineering
in this study moved it.

### 2. Is it a trend signal? No — it is the exact opposite.

Every informative feature has a **negative** information coefficient:

| feature | IC vs next-day return | t |
|---|---:|---:|
| distance above 20-DMA | −0.0266 | −9.16 |
| 5-day return | −0.0283 | −10.31 |
| close near 20-day high | −0.0157 | −5.46 |
| RSI(14) | −0.0236 | −8.36 |
| consecutive up days | −0.0222 | −10.31 |
| closing strength within the day's range | −0.0238 | −10.52 |

Yesterday's strongest names underperform tomorrow. **Buying breakouts and names
pressed against resistance is on the wrong side of the only effect in the data.**
The tradeable version of this signal buys what just fell.

This was checked against the artifact that manufactures it. A closing print
lands at either the bid or the ask, and that error inflates today's return while
deflating tomorrow's — fake reversal out of pure noise. Scoring the same
features against targets that share no price with them:

| feature | IC vs close→close | IC vs open→close | IC vs close(D+1)→close(D+2) |
|---|---:|---:|---:|
| 1-day return | −0.0251 | −0.0305 | **−0.0201** (t −8.42) |
| 5-day return | −0.0283 | −0.0223 | **−0.0235** (t −8.68) |
| distance above 20-DMA | −0.0266 | −0.0208 | **−0.0202** (t −7.12) |

Roughly 20% of the measured reversal is bid-ask artifact; the rest survives with
no shared price at all. **The effect is real.**

### 3. Can it say how far a stock will move? Size yes, direction no.

| | r | R² |
|---|---:|---:|
| today's ATR% → tomorrow's high−low range | **0.491** | 0.241 |
| today's ATR% → tomorrow's absolute return | 0.305 | 0.093 |
| model score → tomorrow's **signed** return | 0.018 | 0.000 |
| model sign agrees with realised sign | | **50.6%** |

This asymmetry is the useful finding of the study. **ATR-derived SL and TP levels
are well founded** — the size of tomorrow's move is genuinely forecastable. The
direction is very nearly a coin flip. So a quoted "expected +4.2%" would be a
volatility estimate with a direction stapled to it, and should not be produced.

### 4. Can the win rate be big? Yes, trivially — and it will mean nothing.

Same picks, same days; only the barriers move. Entry at next open, stops in ATR
multiples, gaps filling at the open, a bar touching both barriers scored as the stop:

| TP/SL (ATR) | days | model win % | **random win %** | model bps | payoff |
|---|---:|---:|---:|---:|---:|
| 2.0 / 1.0 | 5 | 46.4 | 44.1 | +31.7 | 1.36 |
| 1.0 / 1.0 | 5 | 51.7 | 50.4 | +17.4 | 1.03 |
| 1.0 / 2.0 | 5 | 58.5 | 57.9 | +35.2 | 0.86 |
| 0.5 / 2.0 | 5 | 71.0 | **72.1** | +12.3 | 0.45 |
| 0.5 / 3.0 | 10 | 80.2 | **81.2** | +35.2 | 0.31 |

**An 80% win rate is available on demand, and random selection reaches it too.**
Win rate measures barrier geometry, not skill: widen the stop against the target
and you win more often and lose more when you lose. Only expectancy separates
the model from the coin, and it is the `bps` column — never the win column.

This is the single most important result for the original brief. A target of
"big win percent" can be met exactly while making no money at all.

---

## Rejected: the 71% overnight strategy

The one leg with a naturally high hit rate is overnight. A random liquid name
gains **+17.8 bps at a 63.3% hit rate** from close to next open, while the
session itself is **−8.5 bps at 45.7%**. Ranking on top of that looked
extraordinary — OOS IC **0.162**, top-5 hit rate **71.5%**, +39.8 bps/day,
positive in **10 of 10** years.

It is not real. Nothing in liquid equities predicts direction that well, and the
features carrying it — `gap_today` (IC +0.098), `atr_pct` (+0.096), `vol_ratio`
(+0.062) — are a portrait of volatility and spread, not a forecast.

The test: a genuine repricing survives the next session; a spread reverses.

| leg | top-5 | universe | edge | t |
|---|---:|---:|---:|---:|
| overnight close(D)→open(D+1) | +39.8 | +19.0 | **+20.9** | 20.05 |
| session open(D+1)→close(D+1) | −27.2 | −10.2 | **−17.0** | −7.01 |
| **full day** close(D)→close(D+1) | +12.1 | +8.6 | **+3.6** | **1.39** |

**83% of the overnight edge is handed back during the next session**, leaving
+3.6 bps at t = 1.39 — not significant. The mechanism is visible directly:

| ATR% quintile | overnight bps | session bps | full-day bps |
|---|---:|---:|---:|
| Q1 (calmest) | 12.2 | −5.0 | 7.0 |
| Q3 | 17.2 | −8.3 | 8.7 |
| Q5 (wildest) | **24.5** | **−11.9** | 12.2 |

The overnight column rises with volatility and the session column falls by
almost the same amount. Wider-spread names show a bigger fake gap and a bigger
fake fade.

Confirmed independently on real traded prints. Using the 50 symbols with 5-minute
data, the overnight leg is **+5.5 bps** measured close-to-open on daily bars but
only **+2.7 bps at 52.2%** from the 15:25 print to the 09:20 print — the two
prices you could actually transact at. Roughly half of it exists only in the
closing print, which is an auction number, not a price you can buy at.

The daily `open` field itself was verified as genuine: it matches the true 09:15
print on 99–100% of days across the 12 symbols checked, within 1 bps.

---

## The finding that changes the design: one day is the wrong horizon

The same out-of-sample picks, held longer. Nothing about the signal changes —
only how long the position is kept:

| hold | top-5 bps | universe | **edge bps** | t (non-overlapping) | edge bps/**day** |
|---|---:|---:|---:|---:|---:|
| 1 day | 20.2 | 8.6 | +11.7 | 5.23 | 11.7 |
| 2 days | 39.7 | 17.1 | +22.6 | **6.28** | 11.3 |
| 5 days | 87.8 | 42.7 | +45.0 | 5.58 | 9.0 |
| 10 days | 159.6 | 85.1 | +74.5 | 3.62 | 7.5 |
| 20 days | 301.9 | 169.3 | **+132.7** | 2.78 | 6.6 |
| 40 days | 573.8 | 338.4 | **+235.5** | 3.29 | 5.9 |

> **Correction, from Part 2.** This table's long-horizon strength is mostly not
> reversal. The walk-forward model behind it includes a turnover (size) feature,
> and size is the dominant factor at 10+ days — and the one most exposed to
> survivorship bias. With size removed and the score ranked *within* turnover
> bands, the 20-day edge falls from +132.7 bps (t 2.78) to **+34.7 bps (t 1.37)**
> and the 40-day figure stops being significant at all. The reversal signal alone
> peaks at 3–10 days. Read the numbers below as the size effect plus reversal,
> not as reversal.

Edge *per day* decays with horizon, but a round trip is paid **once per trade,
not once per day**. What has to clear the cost hurdle is the third column. At one
day there is ~12 bps of edge against a 27–104 bps round trip at small size — the
trade is under water roughly 3–8x over before the signal is even consulted. By
20 days there is +133 bps against the same fixed toll.

**The signal is fine. The holding period in the brief is what does not work.**

---

## What is worth building

Ranked by what the measurements support, not by what was asked for.

**A. Reversal screener, 10–20 day hold, delivery (CNC).** The measured result.
Buys weakness rather than strength, holds long enough that one round trip is
amortised over +75 to +133 bps of edge. Deliverable is still a daily ranked list
with ATR-derived SL/TP — the request, with the hold extended.

**B. The same list, 1-day hold, paper only.** Honest expectation: ~51.6% hit
rate and ~+12 bps/day before costs, which is negative after them at ₹5,000. Worth
running on paper purely to confirm the live signal matches the study; not worth
funding.

**C. Not worth building:** anything that buys strength/breakouts at a 1-day
horizon (wrong sign), anything premised on the overnight gap (spread), and any
output that quotes an expected percentage move with a direction attached
(direction R² ≈ 0).

### What the list can honestly carry

| column | supported? |
|---|---|
| ranked list of names | yes — OOS IC +0.025, 9/10 years |
| direction (long) | yes, weakly — 51.6% vs 50.5% base |
| SL and TP levels | **yes** — ATR forecasts tomorrow's range at r = 0.49 |
| "expected to move +X%" | **no** — signed R² ≈ 0.000, sign agreement 50.6% |
| a win rate target | only alongside payoff; win % alone is a free parameter |

---

## Data

**No refresh is required.** Daily covers 2011-08-24 → 2026-08-21 across 205
symbols; 5-minute covers 50 symbols over 2 years and was used here only as an
independent check on the closing print.

Two things would materially improve a build, neither available from the current
feed:

1. **Survivorship.** The universe is today's index membership applied to
   history, so companies that failed are absent. This inflates every long-only
   result here, including the benchmark. It cannot be fixed without a
   point-in-time constituent history.
2. **A bid-ask spread series.** Half the "overnight edge" was spread. Having the
   actual quoted spread would let cost be modelled per name instead of assumed
   flat — and would sharpen the eligibility filter more than any new feature.

---

## Manual items

1. **Confirm the intended holding period.** The brief says next-day; the data
   says 10–20 days. This is the one decision that changes what gets built, and it
   is not mine to make.
2. **Confirm whether short selling is in scope.** The brief says "buy or sell".
   NSE cash delivery cannot be shorted — a short must be intraday MIS, squared
   off the same session, which is precisely the leg measured at −8.5 bps/day for
   the universe. The reversal signal's short side was not separately validated.
3. **Confirm capital.** At ₹5,000 the fixed DP charge alone is 47 bps per
   position and no 1-day edge survives. Nothing else moves the economics as much.

---

# Part 2 — the build, and its rejection

The feasibility study said: real but weak signal, reversal not trend, 10–20 day
horizon. That was built as `strategies/reversal.py` and gated by
`backtest/nextday/test_reversal.py` against six criteria written before the run.

**It cleared all six on 13 years of development data and failed to replicate on
the sealed holdout.** The holdout is spent.

## Development window (2011-08 → 2024-08)

| # | criterion | result | |
|---|---|---|---|
| G1 | edge > 0, non-overlapping t > 2 | **+27.3 bps** per 10-day window, t = 2.29 | PASS |
| G2 | top-5 ≥ top-20 ≥ universe ≥ bottom-5 | 118.4 / 109.7 / 91.1 / 82.6 | PASS |
| G3 | beats ≥ 19 of 20 random seeds | **20 of 20** | PASS |
| G4 | positive in ≥ 7 of last 10 years | 8 of 10 | PASS |
| G5 | composite ≥ best single component | +27.3 vs +23.0 | PASS |
| G6 | not a disguised small-cap bet | size-neutral, still t = 2.29 | PASS |

The book — 5 names, 10-day cycle, entered at the close, exited on time:

| | CAGR | max DD | bps/trade | win rate |
|---|---:|---:|---:|---:|
| strategy | **33.96%** | **−35.53%** | +135.2 (t = 4.15) | 55.9% |
| equal-weight universe | 22.91% | −37.47% | | |

## Sealed holdout (2024-08 → 2026-08) — the rejection

| # | result | |
|---|---|---|
| G1 | **+8.7 bps, t = 0.94** | FAIL |
| G2 | top-20 (26.6) > top-5 (21.2) | FAIL |
| G3 | beats **20 of 20** random seeds | PASS |
| G4 | 3 calendar years in a 24-month window | not evaluable |
| G5 | best single (+31.6, t 0.05) > composite | FAIL |
| G6 | fails with G1 | FAIL |

**This is a real failure, not an underpowered window.** The holdout's standard
error is 9.2 bps, so the development edge of +27.3 bps would have printed
**t = 2.97** there. The window could have confirmed it and did not.

What survived: the screener still beat **20 of 20** random seeds, and the bottom
of the ranking was still the worst bucket (−7.6 bps against +12.5 for the
universe). The **sign** of the effect is intact; the **magnitude** is not
tradeable.

The likeliest reading is a weak real effect whose in-sample size was inflated
because the design — horizon, components, pick count — was selected on the same
window it was scored on. The feasibility study measured that design space
explicitly: 17 features × 5 horizons, 3 composites, 6 pick counts, 8 exit rules.
A t of 2.29 on the best of that many looks is not a t of 2.29.

## Two findings that outlived the strategy

**1. Stops make a mean-reversion book worse — including its drawdown.**

| exit rule | bps/trade | CAGR | max DD | stopped out |
|---|---:|---:|---:|---:|
| time only | **+135.2** | **33.96%** | **−35.53%** | 0% |
| stop 2.5 ATR, no target | +115.0 | 30.52% | −33.55% | 17.4% |
| stop 3.0 ATR, no target | +95.1 | 23.55% | −41.75% | 11.5% |
| stop 2.0 / target 3.0 | +85.6 | 24.82% | −46.03% | 24.6% |

A stop sells exactly what the signal bought — more weakness — and realises the
loss the position existed to recover. The freed slot then buys the next falling
name, so the drawdown is not even reduced. **SL/TP levels are still worth
computing as sizing and risk context; they are not an exit rule for this signal.**

**2. Entry timing is worth ~3 points of CAGR.** Same picks, same days: buying at
the next open returned 30.99% against 33.96% for buying into the close. The gap
is the overnight move, which the close-to-close benchmark keeps and an open entry
forfeits — the same effect that killed the overnight strategy in Part 1, seen
from the other side.

## Where this leaves things

- **Do not fund this.** `strategies/reversal.py` prints the holdout verdict
  before it prints a list.
- **The only clean test left is forward time** — paper trading. Every historical
  window in this data has now been used to either design or reject.
- **The strongest raw factor in the data remains size** (turnover, negative sign:
  +62.7 bps at t = 3.87 on the development window). It is excluded on purpose and
  cannot be cleared without a point-in-time constituent list, which the free feed
  does not provide. If that list can be obtained it is the highest-value next
  step — it would either legitimise the strongest effect here or kill it.
- **The 5-day horizon was the only one that held up in the holdout** (+16.6 bps,
  t = 2.08). That is a post-hoc observation on a spent window and cannot be
  claimed as a result; it would need a fresh forward test to mean anything.
