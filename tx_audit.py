import os
import json
import logging
from datetime import datetime, timedelta, timezone
from core.exchange_connector import ExchangeConnector
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("TxAudit")

load_dotenv()

def audit_recent_orders():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)

    from_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    to_time = datetime.now(timezone.utc).isoformat()

    logger.info(f"Fetching all transactions since {from_time}...")
    txs = exchange.get_account_transactions(from_time, to_time)
    logger.info(f"Found {len(txs)} total transactions.")

    # Let's list all transactions to see what's actually happening
    print(f"\n{'Time':<25} | {'Type':<20} | {'OrderID':<15} | {'TradeID':<15}")
    print("-" * 80)
    for tx in txs:
        print(f"{tx.get('time', 'N/A'):<25} | {tx.get('type', 'N/A'):<20} | {tx.get('orderID', 'N/A'):<15} | {tx.get('tradeID', 'N/A'):<15}")

if __name__ == "__main__":
    audit_recent_orders()
