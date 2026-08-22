# Run at home — refreshing the daily data

**The fetch is done.** 205 Nifty 200 symbols, 15.0 years of daily bars (2011-08-24 → 2026-08-21), committed under `data/daily/`. Everything in this repo now reproduces with no network and no credentials.

This document is what you run when the data needs to be **brought up to date** — the strategy holds names for ~2.3 months, so a stale file quietly means stale rankings.

**Why it can't run here:** Angel One's API is firewalled on the OMA Emirates network (`apiconnect.angelone.in` → `208.91.112.55`, Fortinet block page). That is a security control — run it on a personal machine, don't route around it.

---

## What you can run anywhere, right now

No network, no `.env`, no fetch. This is the whole result:

```bash
python backtest/test_portfolio_sanity.py       # 16/16, or nothing below means anything
python data/corporate_actions.py               # what gets repaired in the price data, and why
python backtest/test_momentum.py               # the main result + year-by-year
python backtest/test_momentum_controls.py      # random and bottom-decile controls
python backtest/walk_forward.py                # criterion 5 + the anti-overfitting test
python backtest/test_permutation.py            # permutation test + Bonferroni
python live/generate_orders.py --force --dry-run --rank-buffer 20   # today's buy list
```

`--dry-run` prints the orders without recording an intended portfolio. Leave it off only when you actually intend to place them.

## Refreshing the data (personal machine)

```bash
git pull
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

`.env` is gitignored, so copy it across manually:

```
SMARTAPI_API_KEY=...
SMARTAPI_CLIENT_CODE=...
SMARTAPI_PIN=...
SMARTAPI_TOTP_SECRET=...
```

Then:

```bash
python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15 --force
```

- ~205 symbols, ~2,000 requests, **roughly 15 minutes**
- Writes `data/daily/<SYMBOL>_1day.csv` and `data/universe_1day_report.txt`
- `--force` is needed to refetch; without it, symbols already present are skipped

Useful flags:

```bash
python data/fetch_universe.py --interval ONE_DAY --symbols TCS,INFY --years 15   # smoke test
python data/fetch_universe.py --interval ONE_DAY --audit-only                     # re-audit, no network
```

## What to check in the report

### a) History depth — resolved

The first pull returned **median 15.0 years**, better than the 2016–2017 floor that was expected. 34 of 205 symbols have under 10 years, all genuine later listings (ADANIGREEN 2018, IRCTC 2019, SBILIFE 2017). Nothing to fix.

### b) Unresolved symbols

Two did not resolve: **GUJGASLTD** and **LTIM**. Both are real Nifty 200 members, so this is a scrip-master naming mismatch rather than a missing company — worth resolving, but 203/205 coverage does not change any conclusion.

Verify `data/nifty200.json` against the live NSE Nifty 200 list when you refresh. Membership changes at semi-annual reviews, and a name dropped from the index but left in the file is survivorship bias walking in the front door.

### c) `suspect_gaps` — handled automatically, but read them anyway

The audit flags any single-day move above 25%. Most flagged entries are **genuine market events**, not data errors:

- March 2020 (COVID) across many names
- 2017-10-25 across PSU banks — the ₹2.11 lakh crore recapitalisation announcement
- YESBANK 2020, IDEA throughout, CGPOWER 2019 — real company-specific collapses

`data/corporate_actions.py` catches the ones that are **not** real, using a much higher bar (≤ −50% or ≥ +100% in one day) and truncating that symbol's history to start after the event:

| Symbol | Date | Step | Cause |
|---|---|---:|---|
| ADANIENT | 2015-06-03 | −80.9% | demerger — holders received shares in the spun-out entities |
| PATANJALI | 2020-01-27 | +406.2% | Ruchi Soya relisting after a 75-day trading halt |
| YESBANK | 2020-03-06 | −56.1% | RBI moratorium — a genuine loss, truncated anyway |

This matters more than it looks. Momentum ranks on trailing 12-month returns, so one unadjusted action puts a phantom stock at the top or bottom of the ranking for **twelve consecutive rebalances**. Leaving them in cost 0.74%/yr of CAGR — the uncorrected run bought PATANJALI at ₹457 on a fabricated signal and sold it at ₹201.

If a refresh flags a **new** symbol at those thresholds, `corporate_actions.py` will pick it up automatically; just confirm the reason before trusting the run.

## Reading the result

In priority order:

1. **Does momentum beat equal-weight buy-and-hold by ≥3%/yr after costs?** Currently **+12.18%/yr**. A long-only strategy making money proves nothing on its own — the market rises.
2. **Do the controls pass?** Momentum must beat ≥19 of 20 random-selection seeds and the bottom decile must be symmetrically worse. Currently **20/20**, bottom decile at 12.21% vs 15.38% random. This is the analog of the randomized-direction test that decided the intraday phase.
3. **Does the recent window agree with the full window?** **+8.92%/yr** over the last 5 years vs +12.18%/yr overall. Read the year-by-year table alongside it: the edge is not concentrated in the early (most survivorship-biased) years, but momentum has genuinely underperformed since 2025 (−8.9% relative that year, flat 2026).
4. **Does walk-forward hold?** 7 of 9 out-of-sample windows won, mean +17.07%/yr, t = 2.47. Note the second half of that script: picking the best in-sample variant each fold **lost** to the fixed baseline by 3.41%/yr, which is why the pre-registered baseline is what gets traded.
5. **Does the permutation test clear the Bonferroni bar?** 0 of 400 time-shuffled runs matched the real edge; z = 6.73.
6. **What is the turnover?** Read `turn/yr%` and `cost%/yr`, not just CAGR.

## Choosing a schedule

Running the script daily is free. **Trading** daily is not:

| Schedule | Turnover/yr | Cost/yr | CAGR |
|---|---:|---:|---:|
| Weekly + rank buffer 10 | 492% | 0.89% | **29.72%** |
| Daily + rank buffer 20 | 497% | 0.90% | 29.54% |
| Monthly (baseline) | 516% | 0.94% | 29.22% |
| Daily + rank buffer 10 | 686% | 1.24% | 28.99% |
| Monthly + rank buffer 10 | 323% | 0.58% | 28.43% |
| Quarterly | 280% | 0.51% | 27.77% |
| Weekly, no buffer | 1,131% | 2.06% | 28.50% |
| **Daily, no buffer** | **2,624%** | **4.85%** | **24.39%** |

Naive daily rebalancing gives up ~4.8%/yr churning names that oscillate across the top-20 boundary. **With `--rank-buffer 20` a daily schedule turns over less than the monthly baseline** and exits faster. So a daily buy list is not a compromise — it just requires the buffer.

```bash
python live/generate_orders.py --rebalance D --rank-buffer 20 --dry-run
```

## The holdout — read this before quoting any number

The trailing 24 months were supposed to stay sealed until exactly one final test. **They did not.** The first real-data run had no holdout handling at all and spanned 2011–2026, so that window was observed in the headline, in the recent-5-year row and in the year-by-year table.

Nothing was *tuned* on it, which makes this weak contamination rather than fatal — but a holdout you have looked at is no longer a holdout. `split_holdout()` in `backtest/portfolio.py` now enforces the boundary in code, and both `walk_forward.py` and `test_permutation.py` respect it.

**The honest remaining out-of-sample test is forward time — paper trading — not a re-labelled slice of history.**
