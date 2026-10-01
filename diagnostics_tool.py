import os
import json
import logging
from datetime import datetime
from pathlib import Path
import sys

# Ensure the project root is in the path
sys.path.append(os.path.join(os.getcwd(), "ai-strategy-lab"))

from core.exchange_connector import ExchangeConnector
from dotenv import load_dotenv
import requests

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Diagnostics")

def run_diagnostics():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    
    if not api_key or not account_id:
        logger.error("Missing OANDA credentials in .env")
        return

    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    
    # --- Part 1: Trades 136 and 144 ---
    # Since get_trade_transactions was replaced by get_account_transactions,
    # we will use a custom lookup for specific tradeIDs via the transactions endpoint
    print("\n=== PART 1: TRADE CLOSURE ANALYSIS (136, 144) ===")
    for tid in ["136", "144"]:
        url = f"{exchange.base_url}/accounts/{account_id}/transactions"
        params = {"tradeID": tid}
        try:
            res = requests.get(url, headers=exchange.headers, params=params, timeout=10)
            if res.status_code == 200:
                txs = res.json().get('transactions', [])
                if txs:
                    print(f"Trade {tid} Transactions:")
                    for tx in txs:
                        print(f"  - {tx.get('type')} | Time: {tx.get('time')} | Details: {tx}")
                else:
                    print(f"Trade {tid}: No transactions found on OANDA.")
            else:
                print(f"Trade {tid}: API Error {res.status_code}")
        except Exception as e:
            print(f"Trade {tid}: Exception {e}")

    # --- Part 2 & 3: Files 158-189 ---
    print("\n=== PART 2 & 3: CANCEL/REJECT & TIMING (158-189) ===")
    trades_dir = Path("data/trades")
    if not trades_dir.exists():
        print("Trades directory not found.")
        return

    for i in range(158, 190):
        file_path = trades_dir / f"{i}.json"
        if not file_path.exists():
            continue
            
        with open(file_path, 'r') as f:
            try:
                data = json.load(f)
                order_id = data.get('order_id')
                recorded_at = data.get('recorded_at', 'N/A')
                
                print(f"File {i}.json | RecordedAt: {recorded_at}", end="")
                
                if order_id:
                    url = f"{exchange.base_url}/accounts/{account_id}/transactions"
                    params = {"orderID": order_id}
                    res = requests.get(url, headers=exchange.headers, params=params, timeout=10)
                    if res.status_code == 200:
                        data_tx = res.json()
                        txs = data_tx.get('transactions', [])
                        found = False
                        for tx in txs:
                            if tx.get('type') in ['ORDER_CANCEL', 'MARKET_ORDER_REJECT']:
                                reason = tx.get('reason', 'No reason provided')
                                print(f" | Status: {tx.get('type')} | Reason: {reason}")
                                found = True
                                break
                        if not found:
                            print(" | Status: No cancel/reject transaction found.")
                    else:
                        print(f" | API Error: {res.status_code}")
                else:
                    print(" | No OrderID found in file.")
                    
            except Exception as e:
                print(f" | Error: {e}")

if __name__ == "__main__":
    run_diagnostics()
