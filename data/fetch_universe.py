"""
Fetch 2 years of 5-minute OHLCV for the full Nifty 50 universe.

Run this from a network that can reach Angel One. The OMA Emirates corporate
network blocks it: apiconnect.angelone.in and margincalculator.angelbroking.com
both resolve to 208.91.112.55 and serve a "Fortiguard SDNS Blocked Page"
certificate, so the fetch has to happen elsewhere.

What this does differently from fetch_historical.py
---------------------------------------------------
1. Requests candles in ~90-day chunks instead of one day per request. Angel
   One allows up to 100 days per call at FIVE_MINUTE. That turns ~24,650
   requests (50 symbols x 493 days) into roughly 450, i.e. minutes rather
   than hours.
2. Resolves symbol -> token automatically from the public scrip master, so
   there is no hand-maintained token table to go stale.
3. Backs off properly on rate-limit responses rather than only on exceptions.
4. Audits every file it writes (duplicates, OHLC violations, session
   integrity, suspicious overnight gaps that indicate unadjusted corporate
   actions) and writes a report you can hand straight back.

Usage
-----
    python data/fetch_universe.py                  # fetch everything
    python data/fetch_universe.py --years 2        # lookback (default 2)
    python data/fetch_universe.py --symbols TCS,INFY
    python data/fetch_universe.py --audit-only     # re-audit existing CSVs
    python data/fetch_universe.py --workers 1      # keep it sequential

Output
------
    data/<SYMBOL>_5min.csv        same schema as the existing 5 files:
                                  datetime,open,high,low,close,volume
                                  datetime is tz-aware IST (+05:30)
    data/universe_fetch_report.txt
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
UNIVERSE_FILE = DATA_DIR / "nifty50.json"
REPORT_FILE = DATA_DIR / "universe_fetch_report.txt"

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

INTERVAL = "FIVE_MINUTE"
CHUNK_DAYS = 90          # Angel One allows 100 for FIVE_MINUTE; 90 is a safety margin
REQUEST_DELAY = 0.45     # ~2.2 req/s, under the documented 3/s historical limit
MAX_RETRIES = 5
BASE_BACKOFF = 2.0

RATE_LIMIT_HINTS = (
    "access rate", "rate limit", "too many", "exceeding access",
)


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


def resolve_tokens(symbols):
    """Map trading symbol -> Angel One token using the public scrip master."""
    print(f"  Downloading scrip master ({SCRIP_MASTER_URL.split('/')[-1]}) ...")
    resp = requests.get(SCRIP_MASTER_URL, timeout=180,
                        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    master = resp.json()
    print(f"  Scrip master rows: {len(master):,}")

    wanted = {s.upper() for s in symbols}
    found, seen = {}, set()

    for row in master:
        if row.get("exch_seg") != "NSE":
            continue
        tsym = (row.get("symbol") or "").upper()
        if not tsym.endswith("-EQ"):
            continue
        root = tsym[:-3]
        if root in wanted and root not in seen:
            found[root] = row.get("token")
            seen.add(root)

    missing = sorted(wanted - seen)
    if missing:
        print(f"  [WARN] Could not resolve {len(missing)}: {', '.join(missing)}")
        print("         Check these against the current Nifty 50 list - a name that "
              "no longer trades under this symbol has probably been renamed or removed.")
    print(f"  Resolved {len(found)}/{len(wanted)} symbols to tokens.")
    return found, missing


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def chunk_ranges(start_date, end_date, days=CHUNK_DAYS):
    cur = start_date
    while cur <= end_date:
        stop = min(cur + timedelta(days=days - 1), end_date)
        yield cur, stop
        cur = stop + timedelta(days=1)


def fetch_chunk(smart, token, start, stop):
    """Fetch one date range. Returns list of rows, or None if it never succeeded."""
    params = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": INTERVAL,
        "fromdate": f"{start:%Y-%m-%d} 09:15",
        "todate": f"{stop:%Y-%m-%d} 15:30",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = smart.getCandleData(params)
        except Exception as exc:
            msg = str(exc)
            result = None
        else:
            if result and result.get("status") and result.get("data") is not None:
                return result["data"]
            msg = (result or {}).get("message", "empty response")

        low = msg.lower()
        if any(h in low for h in ("no data", "no record")):
            return []

        if attempt < MAX_RETRIES:
            wait = BASE_BACKOFF * (2 ** (attempt - 1))
            if any(h in low for h in RATE_LIMIT_HINTS):
                wait *= 3          # rate limited: back off hard
            print(f"      retry {attempt}/{MAX_RETRIES} ({msg[:70]}) waiting {wait:.0f}s")
            time.sleep(wait)
        else:
            print(f"      [FAIL] {start}..{stop}: {msg[:90]}")
            return None
    return None


def fetch_symbol(smart, symbol, token, start_date, end_date):
    rows, failures = [], 0
    ranges = list(chunk_ranges(start_date, end_date))

    for i, (a, b) in enumerate(ranges, 1):
        data = fetch_chunk(smart, token, a, b)
        if data is None:
            failures += 1
        elif data:
            rows.extend(data)
        print(f"    {symbol}: chunk {i}/{len(ranges)}  {a}..{b}  "
              f"total {len(rows):,} candles")
        time.sleep(REQUEST_DELAY)

    if not rows:
        return pd.DataFrame(), failures

    df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = (df.sort_values("datetime")
            .drop_duplicates(subset=["datetime"], keep="first")
            .reset_index(drop=True))
    return df, failures


# --------------------------------------------------------------------------
# audit  (mirrors phase-1-backtesting.md section 3)
# --------------------------------------------------------------------------

def audit(df, symbol):
    out = {"symbol": symbol, "rows": len(df)}
    if df.empty:
        out["status"] = "EMPTY"
        return out

    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d["date"] = d["datetime"].dt.date

    out["days"] = d["date"].nunique()
    out["start"] = str(d["datetime"].min())
    out["end"] = str(d["datetime"].max())
    out["dupes"] = int(d["datetime"].duplicated().sum())
    out["zero_vol"] = int((d["volume"] == 0).sum())
    out["ohlc_bad"] = int((
        (d["high"] < d["low"]) | (d["high"] < d["open"]) | (d["high"] < d["close"]) |
        (d["low"] > d["open"]) | (d["low"] > d["close"])
    ).sum())

    per_day = d.groupby("date").size()
    out["short_days"] = int((per_day < 75).sum())

    first_tod = d.groupby("date")["datetime"].first().dt.strftime("%H:%M")
    out["bad_open"] = int((first_tod != "09:15").sum())

    daily = d.groupby("date").agg(op=("open", "first"), cl=("close", "last"))
    gap = (daily["op"] / daily["cl"].shift(1) - 1) * 100
    big = gap[gap.abs() > 15].dropna()
    out["suspect_gaps"] = len(big)
    out["suspect_detail"] = "; ".join(f"{i}:{v:+.1f}%" for i, v in big.items()) if len(big) else ""

    problems = (out["dupes"] or out["ohlc_bad"] or out["bad_open"] or out["suspect_gaps"])
    out["status"] = "CHECK" if problems else "OK"
    return out


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--symbols", type=str, default=None,
                    help="Comma-separated override, e.g. TCS,INFY")
    ap.add_argument("--audit-only", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Refetch even if the CSV already exists")
    args = ap.parse_args()

    universe = json.loads(UNIVERSE_FILE.read_text())["symbols"]
    if args.symbols:
        universe = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("=" * 70)
    print("   Nifty 50 universe fetch - 5-minute candles")
    print("=" * 70)

    if args.audit_only:
        reports = []
        for sym in universe:
            path = DATA_DIR / f"{sym}_5min.csv"
            if path.exists():
                reports.append(audit(pd.read_csv(path), sym))
        write_report(reports, [])
        return

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=int(args.years * 365))
    print(f"Range: {start_date} -> {end_date}   ({args.years} years)")
    print(f"Symbols: {len(universe)}")

    creds = load_credentials()
    tokens, missing = resolve_tokens(universe)
    smart = authenticate(creds)

    reports = []
    for n, sym in enumerate(sorted(tokens), 1):
        path = DATA_DIR / f"{sym}_5min.csv"
        if path.exists() and not args.force:
            print(f"\n[{n}/{len(tokens)}] {sym}: exists, skipping (use --force to refetch)")
            reports.append(audit(pd.read_csv(path), sym))
            continue

        print(f"\n[{n}/{len(tokens)}] {sym} (token {tokens[sym]})")
        df, failures = fetch_symbol(smart, sym, tokens[sym], start_date, end_date)

        if df.empty:
            print(f"  [SKIP] no data for {sym}")
            reports.append({"symbol": sym, "rows": 0, "status": "EMPTY"})
            continue

        df.to_csv(path, index=False)
        rep = audit(df, sym)
        rep["failed_chunks"] = failures
        reports.append(rep)
        print(f"  [SAVED] {path.name}  {rep['rows']:,} candles, {rep['days']} days, "
              f"status={rep['status']}")

    write_report(reports, missing)


def write_report(reports, missing):
    df = pd.DataFrame(reports)
    pd.set_option("display.width", 250)

    cols = [c for c in ["symbol", "rows", "days", "start", "end", "dupes", "ohlc_bad",
                        "bad_open", "short_days", "zero_vol", "suspect_gaps", "status"]
            if c in df.columns]

    lines = []
    lines.append("=" * 100)
    lines.append("  UNIVERSE FETCH REPORT")
    lines.append("=" * 100)
    lines.append(df[cols].to_string(index=False))

    if "status" in df.columns:
        bad = df[df["status"] != "OK"]
        lines.append("")
        lines.append(f"OK: {int((df['status'] == 'OK').sum())}/{len(df)}")
        if len(bad):
            lines.append("\nNEEDS ATTENTION:")
            for _, r in bad.iterrows():
                detail = r.get("suspect_detail", "")
                lines.append(f"  {r['symbol']}: status={r['status']} "
                             f"suspect_gaps={r.get('suspect_gaps', 0)} {detail}")
            lines.append("\nA >15% overnight gap almost always means an unadjusted split or")
            lines.append("bonus. That fabricates a huge fake signal for a gap strategy, so")
            lines.append("fix or drop those symbols before backtesting them.")

    if missing:
        lines.append(f"\nUNRESOLVED SYMBOLS ({len(missing)}): {', '.join(missing)}")

    text = "\n".join(lines)
    print("\n" + text)
    REPORT_FILE.write_text(text, encoding="utf-8")
    print(f"\nReport written to: {REPORT_FILE}")


if __name__ == "__main__":
    main()
