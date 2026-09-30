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

def get_open_positions():
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/positions"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get('positions', [])
    return None

def get_closed_trades():
    # We search for all trades. OANDA /trades returns a list.
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/trades"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get('trades', [])
    return None

def get_trade_details(trade_id):
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/trades/{trade_id}"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get('trade')
    return None

def main():
    print("--- Open Positions ---")
    open_pos = get_open_positions()
    if open_pos is None:
        print("Failed to fetch open positions")
    elif not open_pos:
        print("No open positions")
    else:
        for p in open_pos:
            print(f"TradeID: {p.get('tradeID')}, Instrument: {p.get('instrument')}, UnrealizedPL: {p.get('unrealizedPL')}")
            # Check for SL/TP orders
            # In OANDA v20, these are often listed as associated orders in the position object or need a separate check
            # The prompt asks for stopLossOrder and takeProfitOrder specifically in the response.
            if 'stopLossOrder' in p:
                print(f"  SL Order: {p['stopLossOrder']}")
            else:
                print("  SL Order: MISSING")
            if 'takeProfitOrder' in p:
                print(f"  TP Order: {p['takeProfitOrder']}")
            else:
                print("  TP Order: MISSING")

    print("\n--- Closed Trades Summary ---")
    closed_trades = get_closed_trades()
    if closed_trades is None:
        print("Failed to fetch closed trades")
    elif not closed_trades:
        print("No closed trades found")
    else:
        print(f"Total Trades found in /trades: {len(closed_trades)}")
        # The user mentioned 144 and 136. Let's see if they are here.
        for t in closed_trades:
            # print(f"ID: {t.get('id')}, PnL: {t.get('realizedPL')}")
            pass

if __name__ == "__main__":
    main()
