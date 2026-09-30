import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class TradeTracker:
    """
    Handles persistence of trade 'DNA' and tracks outcomes.
    Stores trades in JSON files within data/trades/
    """
    def __init__(self, storage_dir: str = "data/trades"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def record_entry(self, trade_id: str, trade_dna: Dict[str, Any]) -> str:
        """
        Saves the initial state of a trade (Entry, Reasoning, Confluence).
        """
        file_path = self.storage_dir / f"{trade_id}.json"

        # Add timestamp of recording
        trade_dna['recorded_at'] = datetime.utcnow().isoformat()
        trade_dna['status'] = 'OPEN'

        try:
            with open(file_path, 'w') as f:
                json.dump(trade_dna, f, indent=4)
            logger.info(f"Trade DNA recorded for {trade_id}")
            return str(file_path)
        except Exception as e:
            logger.error(f"Failed to record trade DNA: {e}")
            return ""

    def update_outcome(self, trade_id: str, outcome_data: Dict[str, Any]):
        """
        Updates a trade record with exit details (Exit Price, PnL, Status).
        """
        file_path = self.storage_dir / f"{trade_id}.json"
        if not file_path.exists():
            logger.warning(f"No record found for trade {trade_id}. Cannot update outcome.")
            return

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            data.update(outcome_data)
            data['status'] = 'CLOSED'
            data['closed_at'] = datetime.utcnow().isoformat()

            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)

            logger.info(f"Trade {trade_id} outcome recorded: {outcome_data.get('pnl', 'Unknown PnL')}")
        except Exception as e:
            logger.error(f"Failed to update trade outcome: {e}")

    def get_all_trades(self) -> List[Dict[str, Any]]:
        """
        Retrieves all recorded trades (OPEN and CLOSED).
        """
        all_trades = []
        for file in self.storage_dir.glob("*.json"):
            try:
                with open(file, 'r') as f:
                    data = json.load(f)
                    data['trade_id'] = file.stem
                    all_trades.append(data)
            except Exception as e:
                logger.error(f"Error reading trade file {file}: {e}")
        return all_trades

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """
        Retrieves all trades currently marked as 'OPEN'.
        """
        open_trades = []
        for file in self.storage_dir.glob("*.json"):
            try:
                with open(file, 'r') as f:
                    data = json.load(f)
                    if data.get('status') == 'OPEN':
                        data['trade_id'] = file.stem
                        open_trades.append(data)
            except Exception as e:
                logger.error(f"Error reading trade file {file}: {e}")
        return open_trades

    def estimate_pnl(self, trade: Dict[str, Any], current_price: float) -> float:
        """
        Calculates an estimated PnL for a trade based on current market price.
        PnL = (Current Price - Entry Price) * Units (for Longs)
        """
        entry_price = trade.get('entry_price')
        units = trade.get('units', 0)

        if entry_price is None or units == 0:
            return 0.0

        # If units > 0, it's a LONG. If units < 0, it's a SHORT.
        return (current_price - entry_price) * units
