import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OANDA_API_KEY")
ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
BASE_URL = "https://api-fxpractice.oanda.com/v3"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

def get_open_positions_raw():
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/positions"
    r = requests.get(url, headers=headers)
    return r.json()

def get_closed_trades_raw():
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/trades"
    r = requests.get(url, headers=headers)
    return r.json()

def main():
    print("--- Open Positions Raw ---")
    open_res = get_open_positions_raw()
    print(json.dumps(open_res, indent=2))

    print("\n--- Closed Trades Raw ---")
    closed_res = get_closed_trades_raw()
    print(json.dumps(closed_res, indent=2))

if __name__ == "__main__":
    main()
