# Run at home — fetch daily bars for the Nifty 200

**Why this exists:** Angel One's API is firewalled on the OMA Emirates network (details at the bottom). Everything else in this project runs fine here — this is the only step that has to happen on a personal machine.

**What changed:** the intraday phase is finished and was rejected (real edge of +11.26 bps against a ~14 bps cost hurdle — see `Learning-T/phase-1-backtesting.md`). The project has pivoted to **delivery/CNC systematic momentum**, which needs *daily* bars over many years rather than 5-minute bars over two.

The 5-minute data you already pulled stays where it is. This adds a separate daily set.

---

## 1. Get the code

```bash
git pull                      # on your personal machine
```

You also need `.env` — it is gitignored, so copy it across manually:

```
SMARTAPI_API_KEY=...
SMARTAPI_CLIENT_CODE=...
SMARTAPI_PIN=...
SMARTAPI_TOTP_SECRET=...
```

## 2. Environment

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

## 3. Smoke test two symbols first

Don't start a 15-minute run before knowing the shape of what comes back:

```bash
python data/fetch_universe.py --interval ONE_DAY --symbols TCS,INFY --years 15
```

Check the printed report. **The key number is `years`** — see §5.

## 4. Full pull

```bash
python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15
```

- ~207 symbols, ~2,000 requests, **roughly 15 minutes**
- Output: `data/daily/<SYMBOL>_1day.csv` (separate folder, the 5-minute set is untouched)
- Report: `data/universe_1day_report.txt`
- Total size ~15–20 MB — far smaller than the 108 MB of 5-minute data

It skips symbols already downloaded, so if it dies partway just run it again. Useful flags:

```bash
python data/fetch_universe.py --interval ONE_DAY --force        # refetch everything
python data/fetch_universe.py --interval ONE_DAY --audit-only   # re-audit, no network
```

## 5. Read the report — three things, in priority order

### a) History depth — the main unknown

The report prints a `HISTORY DEPTH` block. Angel One's daily history reportedly starts around 2016–2017 for many instruments, and 15 years may simply not be available.

This matters because a 12-month momentum lookback consumes the first year, and the strategy needs to be tested across regimes that actually break momentum (2018's mid-cap collapse, the 2020 COVID crash, 2022). **If the median depth comes back at 9 years rather than 15, that's workable — we shorten the test window and say so.** What we must not do is pretend the depth is there.

### b) Unresolved symbols

Listed at the bottom of the report. `data/nifty200.json` is my best list of current constituents, but **verify it against the live NSE Nifty 200 list** — index membership changes at semi-annual reviews. A name that was dropped but left in the list, or renamed, is survivorship bias walking in the front door.

### c) `suspect_gaps` — the one that would silently ruin the result

On daily bars an unadjusted split or bonus shows up as a clean −50% / −80% single-day step. The audit flags any single-day move above 25%.

This matters more here than it did intraday: **momentum ranks on trailing 12-month returns**, so one unadjusted corporate action parks a phantom stock at the very top or very bottom of the ranking every single month for a year. Fix or drop any symbol that gets flagged.

Also check `dupes`, `ohlc_bad` and `max_gap_days` are all 0 / small.

## 6. Run the backtests — no network needed

These work anywhere, including back on the work machine:

```bash
python backtest/test_portfolio_sanity.py       # 14 checks, must be 14/14 first
python backtest/test_momentum.py               # the main result
python backtest/test_momentum_controls.py      # does the ranking carry information
```

**Run the sanity suite first.** If it isn't 14/14, nothing downstream means anything.

### What to look for, in priority order

1. **Does momentum beat equal-weight buy-and-hold by ≥3%/yr after costs?** That is the whole question. A long-only strategy making money proves nothing — the market rises. The 3% margin exists because survivorship bias is plausibly worth ~2%.
2. **Does the control pass?** Momentum must beat ≥19 of 20 random-selection seeds, and the bottom decile must be symmetrically worse. This is the analog of the randomized-direction test that decided the intraday phase — if random picks from the same eligible, in-trend pool do as well, the ranking adds nothing.
3. **Does the recent-5-year window agree with the full window?** A large gap is a survivorship-bias signature.
4. **What is the turnover?** Read `turn/yr%` and `cost%/yr`, not just CAGR. Turnover is the dominant cost lever and where an implementation error would hide.

Then send back `backtest/results/momentum_summary.csv`, `backtest/results/momentum_controls.csv` and `data/universe_1day_report.txt`.

**Do not touch the out-of-sample holdout.** The most recent 24 months are reserved for exactly one test at the very end.

## 7. Getting the actual buy list

Once the data is in place:

```bash
python live/generate_orders.py                              # month-end schedule
python live/generate_orders.py --rebalance D --rank-buffer 10   # check daily
python live/generate_orders.py --force                      # initial build
```

It prints SELL and BUY lists with quantities and an estimated cost, and writes `live/orders_<date>.csv`. It uses the *same* `select()` function the backtest calls, so there is no separate live implementation to drift out of sync.

**On running it daily:** checking daily is free, trading daily is not. Measured turnover and cost by schedule:

| Schedule | Turnover/yr | Cost/yr |
|---|---:|---:|
| Monthly + rank buffer | 216% | **1.32%** |
| Monthly | 364% | 2.04% |
| Weekly + rank buffer | 338% | 2.10% |
| Daily + rank buffer | 527% | 3.03% |
| **Daily, no buffer** | **2,161%** | **9.52%** |

Naive daily rebalancing costs more than the entire expected premium. If you want a daily list, always pair it with `--rank-buffer 10`.

---

## The blocker, for the record

```
apiconnect.angelone.in            -> 208.91.112.55
margincalculator.angelbroking.com -> 208.91.112.55
TLS certificate: CN=Fortiguard SDNS Blocked Page, O=Fortinet
```

FortiGuard DNS filtering sinkholes Angel One's domains on the corporate network, almost certainly under a finance/trading category rule. This is a security control — run elsewhere or request an IT exception, don't route around it.

Worth knowing: Phase 3 assumes a static-IP host on AWS `ap-south-1` anyway, so live trading was never going to run from the work network.
