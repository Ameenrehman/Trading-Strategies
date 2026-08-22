"""
Fetch historical intraday OHLCV data from Angel One SmartAPI.

Pulls 5-minute candles for stocks defined in data/instruments.json,
saves to CSV in data/ directory. Paginates day-by-day and skips
NSE holidays using pandas_market_calendars.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal
import pyotp
from dotenv import load_dotenv
from SmartApi.smartConnect import SmartConnect


# --- Configuration ---
INTERVAL = "FIVE_MINUTE"
LOOKBACK_YEARS = 2
DATA_DIR = Path(__file__).parent
INSTRUMENTS_FILE = DATA_DIR / "instruments.json"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds (doubles on each retry)
REQUEST_DELAY = 0.35  # seconds between API calls to respect rate limits


def load_credentials():
    """Load SmartAPI credentials from .env file."""
    load_dotenv(Path(__file__).parent.parent / ".env")
    api_key = os.getenv("SMARTAPI_API_KEY")
    client_code = os.getenv("SMARTAPI_CLIENT_CODE")
    pin = os.getenv("SMARTAPI_PIN") or os.getenv("SMARTAPI_PASSWORD")
    totp_secret = os.getenv("SMARTAPI_TOTP_SECRET")

    missing = []
    if not api_key:
        missing.append("SMARTAPI_API_KEY")
    if not client_code:
        missing.append("SMARTAPI_CLIENT_CODE")
    if not pin:
        missing.append("SMARTAPI_PIN")
    if not totp_secret:
        missing.append("SMARTAPI_TOTP_SECRET")
    if missing:
        print(f"[ERROR] Missing credentials: {', '.join(missing)}")
        sys.exit(1)

    return api_key, client_code, pin, totp_secret


def authenticate(api_key, client_code, pin, totp_secret):
    """Authenticate with SmartAPI and return the SmartConnect object."""
    smart_api = SmartConnect(api_key=api_key)
    totp = pyotp.TOTP(totp_secret.replace(" ", "")).now()

    print(f"  Authenticating as {client_code}...")
    session = smart_api.generateSession(client_code, pin, totp)

    if not session.get("status"):
        print(f"[ERROR] Auth failed: {session.get('message')} (code: {session.get('errorcode')})")
        sys.exit(1)

    print("  [OK] Authenticated successfully.")
    return smart_api


def get_trading_days(start_date, end_date):
    """Get NSE trading days between start and end dates."""
    nse = mcal.get_calendar("XNSE")
    schedule = nse.schedule(start_date=start_date, end_date=end_date)
    return schedule.index.date.tolist()


def fetch_candles_for_day(smart_api, token, exchange, date_obj, interval=INTERVAL):
    """
    Fetch intraday candles for a single trading day.
    Returns a list of [timestamp, O, H, L, C, V] rows, or None on failure.
    """
    from_dt = f"{date_obj.strftime('%Y-%m-%d')} 09:15"
    to_dt = f"{date_obj.strftime('%Y-%m-%d')} 15:30"

    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": interval,
        "fromdate": from_dt,
        "todate": to_dt,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = smart_api.getCandleData(params)
            if result and result.get("status") and result.get("data"):
                return result["data"]
            elif result and result.get("message"):
                msg = result.get("message", "")
                # "No data" is normal for holidays/non-trading days
                if "no data" in msg.lower() or "no record" in msg.lower():
                    return []
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * (2 ** (attempt - 1))
                    print(f"    Retry {attempt}/{MAX_RETRIES} for {date_obj} (msg: {msg}), waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"    [WARN] Failed after {MAX_RETRIES} retries for {date_obj}: {msg}")
                    return None
            else:
                return []
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY * (2 ** (attempt - 1))
                print(f"    Retry {attempt}/{MAX_RETRIES} for {date_obj} (error: {e}), waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    [WARN] Exception after {MAX_RETRIES} retries for {date_obj}: {e}")
                return None

    return None


def fetch_stock_data(smart_api, symbol, token, exchange, trading_days):
    """
    Fetch full historical data for one stock across all trading days.
    Returns a pandas DataFrame.
    """
    all_candles = []
    total_days = len(trading_days)
    failed_days = 0

    for i, day in enumerate(trading_days):
        candles = fetch_candles_for_day(smart_api, token, exchange, day)

        if candles is None:
            failed_days += 1
        elif candles:
            all_candles.extend(candles)

        # Progress update every 50 days
        if (i + 1) % 50 == 0 or (i + 1) == total_days:
            print(f"    {symbol}: {i+1}/{total_days} days fetched ({len(all_candles)} candles so far)")

        # Rate limiting
        time.sleep(REQUEST_DELAY)

    if not all_candles:
        print(f"  [WARN] No candles retrieved for {symbol}!")
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df = df.drop_duplicates(subset=["datetime"], keep="first")

    if failed_days > 0:
        print(f"  [WARN] {symbol}: {failed_days}/{total_days} days had fetch failures")

    return df


def main():
    print("=" * 60)
    print("   SmartAPI Historical Data Fetcher")
    print("=" * 60)

    # Load instruments
    with open(INSTRUMENTS_FILE) as f:
        instruments = json.load(f)["stocks"]
    print(f"\nStocks to fetch: {[s['symbol'] for s in instruments]}")

    # Date range
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=LOOKBACK_YEARS * 365)
    print(f"Date range: {start_date} to {end_date} (~{LOOKBACK_YEARS} years)")

    # Get trading days
    trading_days = get_trading_days(start_date, end_date)
    print(f"NSE trading days in range: {len(trading_days)}")

    if not trading_days:
        print("[ERROR] No trading days found!")
        sys.exit(1)

    # Authenticate
    api_key, client_code, pin, totp_secret = load_credentials()
    smart_api = authenticate(api_key, client_code, pin, totp_secret)

    # Fetch data for each stock
    for stock in instruments:
        symbol = stock["symbol"]
        token = stock["token"]
        exchange = stock["exchange"]
        csv_path = DATA_DIR / "intraday_5min" / f"{symbol}_5min.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"\n--- Fetching {symbol} (token: {token}) ---")

        # Check if file already exists
        if csv_path.exists():
            existing = pd.read_csv(csv_path)
            print(f"  Existing file found: {len(existing)} rows")
            last_date = pd.to_datetime(existing["datetime"]).max().date()
            # Only fetch days after the last existing date
            remaining_days = [d for d in trading_days if d > last_date]
            if not remaining_days:
                print(f"  Already up to date, skipping.")
                continue
            print(f"  Fetching {len(remaining_days)} new days (after {last_date})...")
            df_new = fetch_stock_data(smart_api, symbol, token, exchange, remaining_days)
            if not df_new.empty:
                df = pd.concat([existing, df_new], ignore_index=True)
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.sort_values("datetime").reset_index(drop=True)
                df = df.drop_duplicates(subset=["datetime"], keep="first")
            else:
                df = existing
        else:
            df = fetch_stock_data(smart_api, symbol, token, exchange, trading_days)

        if df.empty:
            print(f"  [SKIP] No data for {symbol}")
            continue

        # Save
        df.to_csv(csv_path, index=False)
        date_range = f"{df['datetime'].iloc[0]} to {df['datetime'].iloc[-1]}"
        n_days = df["datetime"].apply(lambda x: pd.to_datetime(x).date() if isinstance(x, str) else x.date()).nunique()
        print(f"  [SAVED] {csv_path.name}: {len(df)} candles, {n_days} trading days")
        print(f"          Range: {date_range}")

    print("\n" + "=" * 60)
    print("  Data fetch complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
