# Run at home — fetch the Nifty 50 universe

**Why this exists:** the 50-symbol data pull cannot run on the OMA Emirates work machine. Angel One's API domains are firewalled (details at the bottom). Everything else in Phase 1 runs fine here — this is the only step that has to happen on an unblocked network.

**Why it matters:** this is the make-or-break experiment for the whole project. The current best strategy shows **+30.7 bps gross / +15.8 bps net per trade** and passes the randomized-entry control — but on only **94 trades** across 5 correlated mega-caps. That is not enough to trust. Widening to 50 symbols takes the sample to roughly 250–400 trades/year, which is what settles whether this is real.

---

## 1. Copy the repo to your personal machine

Everything needed is already committed in the project folder. Copy the whole tree, or pull it if you push it to a remote.

You need `.env` too — it is gitignored, so copy it across manually. It must contain:

```
SMARTAPI_API_KEY=...
SMARTAPI_CLIENT_CODE=...
SMARTAPI_PIN=...
SMARTAPI_TOTP_SECRET=...
```

## 2. Set up the environment

The bundled `.venv` is tied to this machine, so make a fresh one:

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

## 3. Run the fetch

```bash
python data/fetch_universe.py
```

**Expected:** ~450 API requests, **about 6 minutes**. It prints progress per symbol per chunk.

Useful flags:

```bash
python data/fetch_universe.py --symbols TCS,INFY   # test on two names first
python data/fetch_universe.py --years 3            # deeper history
python data/fetch_universe.py --force              # refetch existing files
python data/fetch_universe.py --audit-only         # re-audit, no network
```

It skips symbols already downloaded, so if it dies partway just run it again.

## 4. Check the report before trusting the data

The script writes `data/universe_fetch_report.txt`. **Read it.** The one thing that would silently wreck this experiment is an **unadjusted split or bonus** — it shows up as a huge fake overnight gap, and the strategy under test is a *gap* strategy, so it would manufacture a spectacular fake edge.

The audit flags:

| Column | Should be | Meaning if not |
|---|---|---|
| `suspect_gaps` | 0 | overnight gap >15% — almost certainly an unadjusted corporate action. Fix or drop the symbol. |
| `dupes` | 0 | duplicate timestamps |
| `ohlc_bad` | 0 | high < low, or open/close outside the bar range |
| `bad_open` | 0 | sessions not starting at 09:15 |
| `days` | ~493 | short counts mean missing history |
| `status` | `OK` | anything else needs a look |

Also check the **unresolved symbols** line at the bottom. `data/nifty50.json` is my best list of current Nifty 50 constituents, but index membership changes at semi-annual reviews and my information may be out of date — **verify it against the live NSE list**. A name that was dropped from the index but left in the list introduces survivorship bias.

## 5. Bring the data back and run the experiment

Copy `data/*_5min.csv` back to the work machine (or just run the backtests at home — they need no network):

```bash
python backtest/test_gap_rvol.py        # the sweep, now on 50 symbols
python backtest/test_gap_controls.py    # randomized-direction control
python backtest/verify_fixes.py         # invariant checks still pass
```

**What to look for**, in priority order:

1. **Does the monotonic gap-size relationship survive?** On 5 symbols, gross edge rose 6.9 → 9.4 → 16.5 → 18.1 → 27.9 bps as the gap threshold went 0.3% → 1.5%. If that shape holds on 50 symbols, it's real. If it flattens or inverts, the 5-symbol result was noise.
2. **Does net edge stay positive with a t-stat above ~2.8?** More symbols means more trades means a tighter t. This is the criterion that currently fails (net t = 2.02).
3. **Does the control still pass?** The real strategy should still beat the randomized-direction seeds, and the inverted variant should still be clearly negative.

Then send me `backtest/results/gap_rvol_summary.csv` and `data/universe_fetch_report.txt` and I'll work through the next stage — walk-forward, the Monte Carlo permutation test, and the go/no-go call.

**Do not touch the out-of-sample holdout yet.** The last 6 months are reserved for exactly one test at the very end.

---

## The blocker, for the record

```
apiconnect.angelone.in           -> 208.91.112.55
margincalculator.angelbroking.com -> 208.91.112.55
TLS certificate: CN=Fortiguard SDNS Blocked Page, O=Fortinet
```

FortiGuard DNS filtering is sinkholing Angel One's domains, almost certainly under a finance/trading category rule. `smartapi.angelone.in` resolves to a real AWS address, but the SDK talks to `apiconnect`, which is blocked. This is a corporate security control — the fix is to run elsewhere or request an exception through IT, not to route around it.

Worth knowing for later: **Phase 3 assumes a static-IP host on AWS `ap-south-1`**, so live trading was never going to run from the work network anyway. This just surfaces that constraint earlier than expected.
