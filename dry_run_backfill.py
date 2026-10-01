import os
import json
import logging
from datetime import datetime
from core.exchange_connector import ExchangeConnector
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("DryRunBackfill")

load_dotenv()

def run_dry_run():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")

    if not api_key or not account_id:
        logger.error("Missing OANDA credentials in environment.")
        return

    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    trades_dir = "data/trades"

    if not os.path.exists(trades_dir):
        logger.error(f"Trades directory {trades_dir} not found.")
        return

    files = [f for f in os.listdir(trades_dir) if f.endswith(".json")]
    logger.info(f"Scanning {len(files)} trade files for dry-run backfill...")

    print(f"\\n{'Local ID':<20} | {'Order ID':<25} | {'Trade ID':<25} | {'Realized PnL':<15}")
    print("-" * 90)

    recovered_count = 0
    unrecoverable_count = 0

    for file_name in sorted(files):
        file_path = os.path.join(trades_dir, file_name)
        with open(file_path, 'r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                continue

        local_id = file_name.replace(".json", "")
        order_id = data.get('order_id')

        if not order_id:
            # No order ID, can't recover from OANDA
            print(f"{local_id:<20} | {'N/A':<25} | {'N/A':<25} | {'N/A':<15}")
            unrecoverable_count += 1
            continue

        # Attempt to resolve Trade ID from Order ID
        trade_id = exchange.get_trade_id_from_order(order_id)

        if trade_id:
            # Attempt to resolve PnL from Trade ID
            details = exchange.get_trade_details(trade_id)
            if details:
                pnl = details.get('realizedPL', 0)
                print(f"{local_id:<20} | {order_id:<25} | {trade_id:<25} | {pnl:<15}")
                recovered_count += 1
            else:
                print(f"{local_id:<20} | {order_id:<25} | {trade_id:<25} | {'Error fetching':<15}")
                unrecoverable_count += 1
        else:
            print(f"{local_id:<20} | {order_id:<25} | {'NOT FOUND':<25} | {'N/A':<15}")
            unrecoverable_count += 1

    print("-" * 90)
    print(f"Dry Run Summary: Total {len(files)} | Recovered {recovered_count} | Unrecoverable {unrecoverable_count}")

if __name__ == "__main__":
    run_dry_run()
