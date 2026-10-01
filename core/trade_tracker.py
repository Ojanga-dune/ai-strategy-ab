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
    def __init__(self, storage_dir: Optional[str] = None):
        # Use absolute path based on project root if no specific dir provided
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            project_root = Path(__file__).parent.parent
            self.storage_dir = project_root / "data" / "trades"

        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def record_entry(self, local_id: str, trade_dna: Dict[str, Any]) -> str:
        """
        Saves the initial state of a trade (Entry, Reasoning, Confluence).
        Uses local_id for the filename to maintain stability.
        """
        # Redirect shadow trades to a separate directory
        storage_path = self.storage_dir
        if trade_dna.get('is_simulated', False):
            project_root = Path(__file__).parent.parent
            storage_path = project_root / "data" / "shadow_trades"
            storage_path.mkdir(parents=True, exist_ok=True)

        file_path = storage_path / f"{local_id}.json"

        # Add timestamp of recording
        trade_dna['recorded_at'] = datetime.utcnow().isoformat()
        trade_dna['status'] = 'OPEN'

        try:
            with open(file_path, 'w') as f:
                json.dump(trade_dna, f, indent=4)
            logger.info(f"Trade DNA recorded for {local_id} (TradeID: {trade_dna.get('trade_id')}) in {storage_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"Failed to record trade DNA: {e}")
            return ""

    def update_outcome(self, local_id: str, outcome_data: Dict[str, Any]):
        """
        Updates a trade record with exit details (Exit Price, PnL, Status).
        """
        # Check both main and shadow storage
        file_path = self.storage_dir / f"{local_id}.json"
        if not file_path.exists():
            project_root = Path(__file__).parent.parent
            file_path = project_root / "data" / "shadow_trades" / f"{local_id}.json"

        if not file_path.exists():
            logger.warning(f"No record found for {local_id} in main or shadow storage. Cannot update outcome.")
            return

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            data.update(outcome_data)
            data['status'] = 'CLOSED'
            data['closed_at'] = datetime.utcnow().isoformat()

            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)

            logger.info(f"Trade {local_id} outcome recorded: {outcome_data.get('pnl', 'Unknown PnL')}")
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
                    data['local_id'] = file.stem
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
                        data['local_id'] = file.stem
                        open_trades.append(data)
            except Exception as e:
                logger.error(f"Error reading trade file {file}: {e}")
        return open_trades

    def save_equity_snapshot(self, equity: float):
        """Persists the start-of-day equity snapshot to disk for compliance recovery."""
        project_root = Path(__file__).parent.parent
        snapshot_path = project_root / "data" / "equity_snapshots"
        snapshot_path.mkdir(parents=True, exist_ok=True)

        filename = f"snapshot_{datetime.utcnow().strftime('%Y-%m-%d')}.json"
        file_path = snapshot_path / filename

        data = {
            "date": datetime.utcnow().strftime('%Y-%m-%d'),
            "equity": equity,
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)
            logger.info(f"Equity snapshot saved: {file_path}")
        except Exception as e:
            logger.error(f"Failed to save equity snapshot: {e}")

    def load_equity_snapshot(self) -> Optional[float]:
        """Loads the equity snapshot for the current date."""
        project_root = Path(__file__).parent.parent
        snapshot_path = project_root / "data" / "equity_snapshots"
        filename = f"snapshot_{datetime.utcnow().strftime('%Y-%m-%d')}.json"
        file_path = snapshot_path / filename

        if not file_path.exists():
            return None

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return float(data.get('equity', 0))
        except Exception as e:
            logger.error(f"Failed to load equity snapshot: {e}")
            return None

