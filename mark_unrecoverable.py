import json
import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataRepair")

def mark_unrecoverable():
    trades_dir = Path("data/trades")
    if not trades_dir.exists():
        logger.error("Trades directory not found.")
        return

    files = list(trades_dir.glob("*.json"))
    logger.info(f"Processing {len(files)} files to mark as unrecoverable...")

    count = 0
    for file in files:
        try:
            with open(file, 'r') as f:
                data = json.load(f)
            
            # Only mark if it's missing both IDs
            if not data.get('order_id') and not data.get('trade_id'):
                data['pnl_source'] = 'unknown'
                data['recovery_status'] = 'UNRECOVERABLE'
                
                with open(file, 'w') as f:
                    json.dump(data, f, indent=4)
                count += 1
        except Exception as e:
            logger.error(f"Error processing {file}: {e}")

    logger.info(f"Successfully marked {count} files as UNRECOVERABLE.")

if __name__ == "__main__":
    mark_unrecoverable()
