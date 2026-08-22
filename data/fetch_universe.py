"""
Fetch historical OHLCV from Angel One SmartAPI for a whole universe of stocks.

Supports both the intraday work (5-minute bars, Nifty 50 — tested and rejected,
see Learning-T/phase-1-backtesting.md) and the current delivery/CNC momentum
work (daily bars, Nifty 200 — see phase-1b-delivery-momentum.md).

Run this from a network that can reach Angel One. The OMA Emirates corporate
network blocks it: apiconnect.angelone.in and margincalculator.angelbroking.com
both resolve to 208.91.112.55 and serve a "Fortiguard SDNS Blocked Page"
certificate, so the fetch has to happen elsewhere. See RUN_AT_HOME.md.

Design notes
------------
1. Candles are requested in chunks rather than one day per request. Angel One's
   documented per-request span is 100 days at FIVE_MINUTE, but forum reports
   suggest responses may also be capped around 500 rows regardless of interval.
   Rather than trusting either number, the fetcher starts with a conservative
   chunk and HALVES IT AND RETRIES whenever a response looks truncated (see
   `_looks_truncated`). Silent truncation is the failure mode that would quietly
   put holes in the history.
2. Symbol -> token resolution comes from the public scrip master, so there is no
   hand-maintained token table to go stale.
3. Every file written is audited. For daily bars the intraday checks (75 bars a
   session, 09:15 open) are meaningless, so a different set runs — coverage,
   continuity, and corporate-action detection.

Usage
-----
    # daily bars for the momentum work (current focus)
    python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15

    # 5-minute bars for the intraday work (historical)
    python data/fetch_universe.py --interval FIVE_MINUTE --universe nifty50 --years 2

    python data/fetch_universe.py --interval ONE_DAY --symbols TCS,INFY   # smoke test
    python data/fetch_universe.py --interval ONE_DAY --audit-only         # no network
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyotp
import requests
from dotenv import load_dotenv
from SmartApi.smartConnect import SmartConnect

DATA_DIR = Path(__file__).parent
PROJECT_ROOT = DATA_DIR.parent

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# Per-interval configuration. `chunk_days` is the STARTING span for one request;
# it is reduced automatically if responses look truncated.
INTERVALS = {
    "ONE_MINUTE":    {"chunk_days": 20,  "suffix": "1min",  "subdir": "minute", "bars_per_day": 375},
    "FIVE_MINUTE":   {"chunk_days": 90,  "suffix": "5min",  "subdir": "intraday_5min", "bars_per_day": 75},
    "FIFTEEN_MINUTE":{"chunk_days": 180, "suffix": "15min", "subdir": "min15",  "bars_per_day": 25},
    "ONE_DAY":       {"chunk_days": 550, "suffix": "1day",  "subdir": "daily",  "bars_per_day": 1},
}

REQUEST_DELAY = 0.45     # ~2.2 req/s, under the documented 3/s historical limit
MAX_RETRIES = 5
BASE_BACKOFF = 2.0
MIN_CHUNK_DAYS = 20

RATE_LIMIT_HINTS = ("access rate", "rate limit", "too many", "exceeding access")


# --------------------------------------------------------------------------
# auth + instrument resolution
# --------------------------------------------------------------------------

def load_credentials():
    load_dotenv(PROJECT_ROOT / ".env")
    creds = {
        "api_key": os.getenv("SMARTAPI_API_KEY"),
        "client_code": os.getenv("SMARTAPI_CLIENT_CODE"),
        "pin": os.getenv("SMARTAPI_PIN") or os.getenv("SMARTAPI_PASSWORD"),
        "totp_secret": os.getenv("SMARTAPI_TOTP_SECRET"),
    }
    missing = [k for k, v in creds.items() if not v]
    if missing:
        sys.exit(f"[ERROR] Missing credentials in .env: {', '.join(missing)}")
    return creds


def authenticate(creds):
    smart = SmartConnect(api_key=creds["api_key"])
    totp = pyotp.TOTP(creds["totp_secret"].replace(" ", "")).now()
    print(f"  Authenticating as {creds['client_code']} ...")
    session = smart.generateSession(creds["client_code"], creds["pin"], totp)
    if not session.get("status"):
        sys.exit(f"[ERROR] Auth failed: {session.get('message')} "
                 f"(code {session.get('errorcode')})")
    print("  [OK] Authenticated.")
    return smart


SYMBOL_ALIASES = {
    "TATAMOTORS": "TMPV",
    "L&TFH": "LTF",
    "PEL": "PIRAMALFIN",
}


def resolve_tokens(symbols):
    """Map trading symbol -> Angel One token using the public scrip master."""
    print(f"  Downloading scrip master ...")
    resp = requests.get(SCRIP_MASTER_URL, timeout=180,
                        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    master = resp.json()
    print(f"  Scrip master rows: {len(master):,}")

    wanted = {s.upper() for s in symbols}
    target_to_sym = {s: s for s in wanted}
    for orig, alias in SYMBOL_ALIASES.items():
        if orig in wanted:
            target_to_sym[alias] = orig

    found, seen = {}, set()

    for row in master:
        if row.get("exch_seg") != "NSE":
            continue
        tsym = (row.get("symbol") or "").upper()
        if not tsym.endswith("-EQ"):
            continue
        root = tsym[:-3]
        if root in target_to_sym:
            orig_sym = target_to_sym[root]
            if orig_sym not in seen:
                found[orig_sym] = row.get("token")
                seen.add(orig_sym)

    missing = sorted(wanted - seen)
    if missing:
        print(f"  [WARN] Could not resolve {len(missing)}: {', '.join(missing)}")
        print("         Check these against the current index constituents — a name")
        print("         that no longer trades under this symbol has been renamed or")
        print("         removed, which is a survivorship-bias red flag.")
    print(f"  Resolved {len(found)}/{len(wanted)} symbols to tokens.")
    return found, missing


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def chunk_ranges(start_date, end_date, days):
    cur = start_date
    while cur <= end_date:
        stop = min(cur + timedelta(days=days - 1), end_date)
        yield cur, stop
        cur = stop + timedelta(days=1)


def _looks_truncated(rows, start, stop, interval):
    """
    Heuristic: did the API silently cut this response short?

    Angel One's per-request limits are documented inconsistently and forum
    reports mention a ~500-row cap. Rather than trusting a number, compare what
    came back against a rough expectation and flag suspiciously round counts.
    A truncated chunk leaves a hole in the history that nothing downstream
    would notice, so this errs toward retrying with a smaller span.
    """
    n = len(rows)
    if n == 0:
        return False
    # Round-number cap is the giveaway.
    if n in (500, 1000, 2000):
        return True
    cal_days = (stop - start).days + 1
    expected = cal_days * (250 / 365) * INTERVALS[interval]["bars_per_day"]
    return expected > 0 and n < expected * 0.55


def fetch_chunk(smart, token, start, stop, interval):
    """Fetch one date range. Returns (rows, truncated) — rows is None on failure."""
    params = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": interval,
        "fromdate": f"{start:%Y-%m-%d} 09:15",
        "todate": f"{stop:%Y-%m-%d} 15:30",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = smart.getCandleData(params)
        except Exception as exc:
            msg, result = str(exc), None
        else:
            if result and result.get("status") and result.get("data") is not None:
                rows = result["data"]
                return rows, _looks_truncated(rows, start, stop, interval)
            msg = (result or {}).get("message", "empty response")

        low = msg.lower()
        if any(h in low for h in ("no data", "no record")):
            return [], False

        if attempt < MAX_RETRIES:
            wait = BASE_BACKOFF * (2 ** (attempt - 1))
            if any(h in low for h in RATE_LIMIT_HINTS):
                wait *= 3
            print(f"      retry {attempt}/{MAX_RETRIES} ({msg[:70]}) waiting {wait:.0f}s")
            time.sleep(wait)
        else:
            print(f"      [FAIL] {start}..{stop}: {msg[:90]}")
            return None, False
    return None, False


def fetch_symbol(smart, symbol, token, start_date, end_date, interval):
    """
    Fetch one symbol across the full range, shrinking the chunk span if the
    API starts truncating responses.
    """
    chunk_days = INTERVALS[interval]["chunk_days"]
    rows, failures, shrinks = [], 0, 0

    ranges = list(chunk_ranges(start_date, end_date, chunk_days))
    i = 0
    while i < len(ranges):
        a, b = ranges[i]
        data, truncated = fetch_chunk(smart, token, a, b, interval)

        if truncated and chunk_days > MIN_CHUNK_DAYS:
            chunk_days = max(MIN_CHUNK_DAYS, chunk_days // 2)
            shrinks += 1
            print(f"    {symbol}: response looked truncated ({len(data)} rows) — "
                  f"reducing chunk to {chunk_days}d and redoing from {a}")
            ranges = ranges[:i] + list(chunk_ranges(a, end_date, chunk_days))
            time.sleep(REQUEST_DELAY)
            continue

        if data is None:
            failures += 1
        elif data:
            rows.extend(data)

        i += 1
        if i % 5 == 0 or i == len(ranges):
            print(f"    {symbol}: chunk {i}/{len(ranges)}  {a}..{b}  "
                  f"total {len(rows):,} bars")
        time.sleep(REQUEST_DELAY)

    if not rows:
        return pd.DataFrame(), failures

    df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = (df.sort_values("datetime")
            .drop_duplicates(subset=["datetime"], keep="first")
            .reset_index(drop=True))
    if shrinks:
        print(f"    {symbol}: chunk span was reduced {shrinks}x during this fetch")
    return df, failures


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------

def audit_intraday(d, symbol):
    """Session-structure checks — only meaningful for intraday bars."""
    out = {}
    per_day = d.groupby("date").size()
    out["short_days"] = int((per_day < 75).sum())
    first_tod = d.groupby("date")["datetime"].first().dt.strftime("%H:%M")
    out["bad_open"] = int((first_tod != "09:15").sum())
    return out


def audit_daily(d, symbol):
    """
    Coverage and continuity checks for daily bars.

    History depth is the key unknown for the momentum work — a 12-month
    lookback plus a meaningful test window needs many years, and Angel One's
    daily history does not reach back equally far for every instrument.
    """
    out = {}
    dates = pd.to_datetime(d["date"])
    out["years"] = round((dates.max() - dates.min()).days / 365.25, 1)
    # Largest run of consecutive missing weekdays — a real hole in the history.
    all_bd = pd.bdate_range(dates.min(), dates.max())
    have = set(dates.dt.normalize())
    missing = [x for x in all_bd if x not in have]
    gap = run = 0
    prev = None
    for m in missing:
        run = run + 1 if prev is not None and (m - prev).days <= 3 else 1
        gap = max(gap, run)
        prev = m
    out["max_gap_days"] = gap
    return out


def audit(df, symbol, interval):
    out = {"symbol": symbol, "rows": len(df)}
    if df.empty:
        out["status"] = "EMPTY"
        return out

    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d["date"] = d["datetime"].dt.date

    out["days"] = d["date"].nunique()
    out["start"] = str(d["datetime"].min().date())
    out["end"] = str(d["datetime"].max().date())
    out["dupes"] = int(d["datetime"].duplicated().sum())
    out["zero_vol"] = int((d["volume"] == 0).sum())
    out["ohlc_bad"] = int((
        (d["high"] < d["low"]) | (d["high"] < d["open"]) | (d["high"] < d["close"]) |
        (d["low"] > d["open"]) | (d["low"] > d["close"])
    ).sum())

    if interval == "ONE_DAY":
        out.update(audit_daily(d, symbol))
        # On daily bars an unadjusted split is a clean step, so the threshold
        # can be tighter than the intraday one.
        daily = d.set_index("date")["close"]
        ret = (daily / daily.shift(1) - 1) * 100
        thresh = 25
    else:
        out.update(audit_intraday(d, symbol))
        g = d.groupby("date").agg(op=("open", "first"), cl=("close", "last"))
        ret = (g["op"] / g["cl"].shift(1) - 1) * 100
        thresh = 15

    big = ret[ret.abs() > thresh].dropna()
    out["suspect_gaps"] = len(big)
    out["suspect_detail"] = "; ".join(f"{i}:{v:+.1f}%" for i, v in big.items()) if len(big) else ""

    problems = out["dupes"] or out["ohlc_bad"] or out["suspect_gaps"] or out.get("bad_open", 0)
    out["status"] = "CHECK" if problems else "OK"
    return out


# --------------------------------------------------------------------------

def out_path(symbol, interval):
    cfg = INTERVALS[interval]
    d = DATA_DIR / cfg["subdir"] if cfg["subdir"] else DATA_DIR
    return d / f"{symbol}_{cfg['suffix']}.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="FIVE_MINUTE", choices=sorted(INTERVALS))
    ap.add_argument("--universe", default=None,
                    help="Name of a JSON file in data/ without the extension, "
                         "e.g. nifty200. Defaults by interval.")
    ap.add_argument("--years", type=float, default=None)
    ap.add_argument("--symbols", type=str, default=None,
                    help="Comma-separated override, e.g. TCS,INFY")
    ap.add_argument("--audit-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    interval = args.interval
    universe_name = args.universe or ("nifty200" if interval == "ONE_DAY" else "nifty50")
    years = args.years if args.years is not None else (15.0 if interval == "ONE_DAY" else 2.0)

    universe_file = DATA_DIR / f"{universe_name}.json"
    if not universe_file.exists():
        sys.exit(f"[ERROR] Universe file not found: {universe_file}")
    universe = json.loads(universe_file.read_text(encoding="utf-8"))["symbols"]
    if args.symbols:
        universe = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("=" * 72)
    print(f"   Universe fetch — {interval} — {universe_name}")
    print("=" * 72)

    report_file = DATA_DIR / f"universe_{INTERVALS[interval]['suffix']}_report.txt"

    if args.audit_only:
        reports = []
        for sym in universe:
            p = out_path(sym, interval)
            if p.exists():
                reports.append(audit(pd.read_csv(p), sym, interval))
        write_report(reports, [], report_file, interval)
        return

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=int(years * 365.25))
    print(f"Range: {start_date} -> {end_date}   ({years} years)")
    print(f"Symbols: {len(universe)}")
    print(f"Output : {out_path('<SYMBOL>', interval)}")

    creds = load_credentials()
    tokens, missing = resolve_tokens(universe)
    smart = authenticate(creds)

    out_dir = out_path("X", interval).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    for n, sym in enumerate(sorted(tokens), 1):
        path = out_path(sym, interval)
        if path.exists() and not args.force:
            print(f"\n[{n}/{len(tokens)}] {sym}: exists, skipping (--force to refetch)")
            reports.append(audit(pd.read_csv(path), sym, interval))
            continue

        print(f"\n[{n}/{len(tokens)}] {sym} (token {tokens[sym]})")
        df, failures = fetch_symbol(smart, sym, tokens[sym], start_date, end_date, interval)

        if df.empty:
            print(f"  [SKIP] no data for {sym}")
            reports.append({"symbol": sym, "rows": 0, "status": "EMPTY"})
            continue

        df.to_csv(path, index=False)
        rep = audit(df, sym, interval)
        rep["failed_chunks"] = failures
        reports.append(rep)
        extra = f", {rep.get('years', '?')}y" if interval == "ONE_DAY" else ""
        print(f"  [SAVED] {path.name}  {rep['rows']:,} bars, {rep['days']} days{extra}, "
              f"status={rep['status']}")

    write_report(reports, missing, report_file, interval)


def write_report(reports, missing, report_file, interval):
    df = pd.DataFrame(reports)
    pd.set_option("display.width", 250)

    if interval == "ONE_DAY":
        cols = ["symbol", "rows", "days", "years", "start", "end", "dupes",
                "ohlc_bad", "max_gap_days", "zero_vol", "suspect_gaps", "status"]
    else:
        cols = ["symbol", "rows", "days", "start", "end", "dupes", "ohlc_bad",
                "bad_open", "short_days", "zero_vol", "suspect_gaps", "status"]
    cols = [c for c in cols if c in df.columns]

    lines = ["=" * 110, f"  UNIVERSE FETCH REPORT — {interval}", "=" * 110,
             df[cols].to_string(index=False), ""]

    if "status" in df.columns:
        lines.append(f"OK: {int((df['status'] == 'OK').sum())}/{len(df)}")

    if interval == "ONE_DAY" and "years" in df.columns:
        y = df["years"].dropna()
        if len(y):
            lines += ["", "HISTORY DEPTH — the key unknown for the momentum work:",
                      f"  median {y.median():.1f}y | min {y.min():.1f}y | max {y.max():.1f}y",
                      f"  symbols with < 10y: {int((y < 10).sum())}/{len(y)}",
                      f"  earliest start across universe: {df['start'].min()}",
                      "",
                      "  A 12-month momentum lookback plus a meaningful test window needs",
                      "  many years. If the median is well under 10, shorten the test",
                      "  window to match rather than pretending the depth is there."]

    if "status" in df.columns:
        bad = df[df["status"] != "OK"]
        if len(bad):
            lines += ["", "NEEDS ATTENTION:"]
            for _, r in bad.iterrows():
                lines.append(f"  {r['symbol']}: status={r['status']} "
                             f"suspect_gaps={r.get('suspect_gaps', 0)} "
                             f"{r.get('suspect_detail', '')}")
            lines += ["",
                      "A large single-day step on daily bars is almost always an",
                      "UNADJUSTED SPLIT OR BONUS. Momentum ranks on trailing returns, so",
                      "one unadjusted action puts a phantom stock at the top or bottom of",
                      "the ranking every month for a year. Fix or drop those symbols."]

    if missing:
        lines += ["", f"UNRESOLVED SYMBOLS ({len(missing)}): {', '.join(missing)}",
                  "  Verify these against the live index constituent list — a renamed or",
                  "  dropped name is a survivorship-bias red flag."]

    text = "\n".join(lines)
    print("\n" + text)
    report_file.write_text(text, encoding="utf-8")
    print(f"\nReport written to: {report_file}")


if __name__ == "__main__":
    main()
