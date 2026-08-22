"""
Smoke-test script for Angel One SmartAPI connection & historical data retrieval.
"""

import os
import sys
from datetime import datetime, timedelta
import pyotp
from dotenv import load_dotenv
from SmartApi.smartConnect import SmartConnect
import pandas as pd

def mask_string(s: str, visible_chars: int = 4) -> str:
    if not s or len(s) <= visible_chars:
        return "****"
    return s[:2] + "*" * (len(s) - visible_chars) + s[-2:]

def run_test():
    # Load environment variables
    load_dotenv()

    api_key = os.getenv("SMARTAPI_API_KEY")
    client_code = os.getenv("SMARTAPI_CLIENT_CODE")
    pin = os.getenv("SMARTAPI_PIN") or os.getenv("SMARTAPI_PASSWORD")
    totp_secret = os.getenv("SMARTAPI_TOTP_SECRET")

    print("=" * 60)
    print("      Angel One SmartAPI Smoke Test & Connectivity Check    ")
    print("=" * 60)

    # Check credentials
    missing = []
    if not api_key or api_key == "your_api_key_here":
        missing.append("SMARTAPI_API_KEY")
    if not client_code or client_code == "your_client_code_here":
        missing.append("SMARTAPI_CLIENT_CODE")
    if not pin or pin == "your_mpin_here":
        missing.append("SMARTAPI_PIN (or SMARTAPI_PASSWORD)")
    if not totp_secret or totp_secret == "your_totp_secret_key_here":
        missing.append("SMARTAPI_TOTP_SECRET")

    if missing:
        print("\n[!] Missing or default values found in .env:")
        for m in missing:
            print(f"   - {m}")
        print("\nPlease update your .env file with your actual Angel One credentials.")
        print("Template available at .env.example\n")
        return

    print("\n[1] Loaded Credentials:")
    print(f"    - API Key     : {mask_string(api_key)}")
    print(f"    - Client Code : {client_code}")
    print(f"    - MPIN/PIN    : {'*' * len(pin)}")
    print(f"    - TOTP Secret : {mask_string(totp_secret)}")

    # 1. Generate TOTP
    try:
        totp = pyotp.TOTP(totp_secret.replace(" ", "")).now()
        print(f"\n[2] Generated current TOTP: {totp}")
    except Exception as e:
        print(f"\n[X] Failed to generate TOTP from secret: {e}")
        print("    Please verify that SMARTAPI_TOTP_SECRET is a valid Base32 key.")
        return

    # 2. Initialize SmartConnect and Generate Session
    print("\n[3] Authenticating with SmartAPI...")
    smart_api = SmartConnect(api_key=api_key)

    try:
        session_data = smart_api.generateSession(client_code, pin, totp)
    except Exception as e:
        print(f"[X] Exception during generateSession: {e}")
        return

    if not session_data.get("status"):
        print(f"[X] Authentication Failed!")
        print(f"    Message   : {session_data.get('message')}")
        print(f"    Error Code: {session_data.get('errorcode')}")
        return

    print("[✓] Authentication Successful!")
    feed_token = smart_api.getfeedToken()
    refresh_token = session_data.get("data", {}).get("refreshToken")
    jwt_token = session_data.get("data", {}).get("jwtToken")
    print(f"    - JWT Token   : {mask_string(jwt_token, 8)}")
    print(f"    - Feed Token  : {mask_string(feed_token, 8)}")

    # 3. Fetch User Profile
    print("\n[4] Fetching User Profile...")
    try:
        profile = smart_api.getProfile(refresh_token)
        if profile and profile.get("status"):
            pdata = profile.get("data", {})
            name = pdata.get("name", "N/A")
            client_id = pdata.get("clientcode", "N/A")
            exchanges = pdata.get("exchanges", [])
            print(f"[✓] Connected Account: {name} (Client: {client_id})")
            print(f"    Active Exchanges: {exchanges}")
        else:
            print(f"[-] Could not retrieve profile details: {profile.get('message')}")
    except Exception as e:
        print(f"[-] Profile fetch error (non-fatal): {e}")

    # 4. Fetch Historical Candle Data (SBIN-EQ 5-min candles test)
    print("\n[5] Testing Historical Candle Data Fetch (SBIN-EQ, 5-min candles)...")
    try:
        # Request past 5 business days
        to_date = datetime.now().strftime("%Y-%m-%d 15:30")
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 09:15")

        historic_param = {
            "exchange": "NSE",
            "symboltoken": "3045",  # SBIN token on NSE
            "interval": "FIVE_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }

        candle_res = smart_api.getCandleData(historic_param)
        if candle_res and candle_res.get("status") and candle_res.get("data"):
            raw_candles = candle_res.get("data")
            df = pd.DataFrame(raw_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            print(f"[✓] Successfully retrieved {len(df)} candles!")
            print("\nRecent 5 Candles Sample:")
            print(df.tail())
            print("\n" + "=" * 60)
            print("  ✓ ALL CHECKS PASSED: SmartAPI is fully ready for Phase 1!")
            print("=" * 60)
        else:
            print(f"[X] Historical data request failed: {candle_res.get('message')}")
    except Exception as e:
        print(f"[X] Error fetching candle data: {e}")

if __name__ == "__main__":
    run_test()
