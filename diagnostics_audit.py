import os
import json
import logging
from datetime import datetime, timezone
from core.exchange_connector import ExchangeConnector
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Diagnostics")

load_dotenv()

def run_diagnostics():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")

    if not api_key or not account_id:
        logger.error("Missing OANDA credentials in environment.")
        return

    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    trades_dir = "data/trades"

    # Time range for transaction fetch - broad enough to cover the legacy trades
    # Using a wide range to ensure we catch all relevant events
    from_time = "2026-01-01T00:00:00Z"
    to_time = datetime.now(timezone.utc).isoformat()

    logger.info(f"Fetching transactions from {from_time} to {to_time}...")
    all_txs = exchange.get_account_transactions(from_time, to_time)
    logger.info(f"Retrieved {len(all_txs)} transactions.")

    # Index transactions by Order ID for fast lookup
    tx_by_order = {}
    for tx in all_txs:
        oid = tx.get('orderID')
        if oid:
            if oid not in tx_by_order:
                tx_by_order[oid] = []
            tx_by_order[oid].append(tx)

    # --- Part 1: Trades 136 and 144 ---
    print("\n=== PART 1: Trades 136 & 144 Closure Audit ===")
    for tid in ["136", "144"]:
        # We need to find the order_id first if we only have local_id
        file_path = os.path.join(trades_dir, f"{tid}.json")
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                data = json.load(f)
            oid = data.get('order_id')
            if oid:
                events = tx_by_order.get(oid, [])
                if events:
                    print(f"Trade {tid} (Order {oid}):")
                    for e in events:
                        print(f"  - {e.get('type')} at {e.get('time')} | Details: {e}")
                else:
                    print(f"Trade {tid} (Order {oid}): No transactions found on broker.")
            else:
                print(f"Trade {tid}: No order_id in file. Cannot audit.")
        else:
            print(f"Trade {tid}: File not found.")

    # --- Part 2: Cancellation Reasons (158-189) ---
    print("\n=== PART 2: Cancellation Reasons (Files 158-189) ===")
    print(f"{'Local ID':<12} | {'Order ID':<25} | {'Reason':<20} | {'Type':<20}")
    print("-" * 80)
    for i in range(158, 190):
        file_path = os.path.join(trades_dir, f"{i}.json")
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                data = json.load(f)
            oid = data.get('order_id')
            if oid:
                events = tx_by_order.get(oid, [])
                # Look for ORDER_CANCEL or MARKET_ORDER_REJECT
                cancel_event = next((e for e in events if e.get('type') in ['ORDER_CANCEL', 'MARKET_ORDER_REJECT']), None)
                if cancel_event:
                    reason = cancel_event.get('reason', 'No reason provided')
                    print(f"{i:<12} | {oid:<25} | {reason:<20} | {cancel_event.get('type'):<20}")
                else:
                    print(f"{i:<12} | {oid:<25} | {'No Cancel/Reject':<20} | {'N/A':<20}")
            else:
                print(f"{i:<12} | {'No Order ID':<25} | {'N/A':<20} | {'N/A':<20}")
        else:
            print(f"{i:<12} | {'File Missing':<25} | {'N/A':<20} | {'N/A':<20}")

    # --- Part 3: recorded_at Time (171-189) ---
    print("\n=== PART 3: recorded_at Timeline (Files 171-189) ===")
    print(f"{'Local ID':<12} | {'recorded_at'}")
    print("-" * 40)
    for i in range(171, 190):
        file_path = os.path.join(trades_dir, f"{i}.json")
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                data = json.load(f)
            print(f"{i:<12} | {data.get('recorded_at', 'N/A')}")
        else:
            print(f"{i:<12} | File Missing")

if __name__ == "__main__":
    run_diagnostics()
