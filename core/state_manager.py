import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class StateManager:
    """
    Handles persistence of the bot's internal state.
    Ensures that after a restart, the bot knows exactly which
    positions it is managing and avoids double-entries.
    """
    def __init__(self, state_file: str = "data/bot_state.json"):
        self.state_path = Path(state_file)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.current_state = self._load_state()

    def get_boot_count(self) -> int:
        """Returns the total number of times the bot has booted."""
        return self.current_state.get("boot_count", 0)

    def save_boot_count(self, count: int):
        """Persists the boot count to disk."""
        with self._lock:
            self.current_state["boot_count"] = count
            self.save_state()

    def _load_state(self) -> Dict[str, Any]:
        """Loads the state from disk on startup."""
        if not self.state_path.exists():
            return {"active_trades": {}, "last_cycle_timestamp": None, "session_start_equity": None, "heartbeat_pending": False, "last_heartbeat_time": None, "heartbeat_due_at": None}

        try:
            with open(self.state_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state file: {e}")
            return {"active_trades": {}, "last_cycle_timestamp": None, "session_start_equity": None, "heartbeat_pending": False, "last_heartbeat_time": None, "heartbeat_due_at": None}

    def save_state(self):
        """
        Persists current state to disk atomically.
        Writes to a temporary file and replaces the original to prevent corruption.
        """
        # This function assumes it is called within self._lock where necessary,
        # but we add a check/internal lock if called externally.
        try:
            # 1. Serialize to string first to validate JSON
            data_str = json.dumps(self.current_state, indent=4)

            # 2. Write to temporary file in the same directory
            temp_file = self.state_path.with_suffix(".tmp")
            with open(temp_file, 'w') as f:
                f.write(data_str)
                f.flush()
                os.fsync(f.fileno()) # Ensure it's on disk

            # 3. Atomic replacement
            os.replace(temp_file, self.state_path)
        except Exception as e:
            logger.error(f"Atomic save failed for state file {self.state_path}: {e}")

    def update_trade(self, trade_id: str, data: Dict[str, Any]):
        """Updates or adds a trade to the active state."""
        with self._lock:
            self.current_state["active_trades"][trade_id] = data
            self.save_state()

    def remove_trade(self, trade_id: str):
        """Removes a trade from active state upon closure."""
        with self._lock:
            if trade_id in self.current_state["active_trades"]:
                del self.current_state["active_trades"][trade_id]
                self.save_state()

    def save_heartbeat_metrics(self, last_time: Optional[datetime], due_at: Optional[datetime], pending: bool = False, retry_count: int = 0, next_retry: Optional[datetime] = None, runtime_state: Any = None):
        """Persists heartbeat timestamps, outage tracking, and component health to disk."""
        with self._lock:
            self.current_state["last_heartbeat_time"] = last_time.isoformat() if last_time else None
            self.current_state["heartbeat_due_at"] = due_at.isoformat() if due_at else None
            self.current_state["heartbeat_pending"] = pending
            self.current_state["heartbeat_retry_count"] = retry_count
            self.current_state["heartbeat_next_retry_at"] = next_retry.isoformat() if next_retry else None

            # Persist outage tracking and health
            if runtime_state:
                self.current_state["outage_generation_id"] = runtime_state.outage_generation_id
                self.current_state["recovery_notified_generation_id"] = runtime_state.recovery_notified_generation_id
                self.current_state["connectivity_health"] = runtime_state.connectivity_health
                self.current_state["is_outage_active"] = runtime_state.is_outage_active

            self.save_state()

    def load_heartbeat_metrics(self) -> Tuple[Optional[datetime], Optional[datetime], bool, int, Optional[datetime], int, int, Dict[str, bool], bool]:
        """Loads persisted heartbeat metrics, outage tracking, and health state."""
        last_time_str = self.current_state.get("last_heartbeat_time")
        due_at_str = self.current_state.get("heartbeat_due_at")
        pending = self.current_state.get("heartbeat_pending", False)
        retry_count = self.current_state.get("heartbeat_retry_count", 0)
        next_retry_str = self.current_state.get("heartbeat_next_retry_at")
        outage_gen = self.current_state.get("outage_generation_id", 0)
        recovery_gen = self.current_state.get("recovery_notified_generation_id", 0)
        health = self.current_state.get("connectivity_health", {"telegram": True, "broker": True})
        outage_active = self.current_state.get("is_outage_active", False)

        last_time = datetime.fromisoformat(last_time_str) if last_time_str else None
        due_at = datetime.fromisoformat(due_at_str) if due_at_str else None
        next_retry = datetime.fromisoformat(next_retry_str) if next_retry_str else None

        return last_time, due_at, pending, retry_count, next_retry, outage_gen, recovery_gen, health, outage_active

    def reconcile_with_broker(self, broker_positions: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Reconciles the internal state with actual broker positions.
        - Trades in state but NOT in broker -> Mark as CLOSED.
        - Trades in broker but NOT in state -> Add to state as 'IMPORTED'.
        Returns (is_synchronized, mismatch_reason).
        """
        with self._lock:
            broker_trade_ids = [p.get('tradeID') for p in broker_positions if p.get('tradeID')]
            state_trade_ids = list(self.current_state["active_trades"].keys())

            mismatches = []

            # 1. Handle trades that were closed on broker but are still in state
            for t_id in state_trade_ids:
                if t_id not in broker_trade_ids:
                    logger.info(f"Reconciliation: Trade {t_id} closed on broker. Removing from active state.")
                    self.remove_trade(t_id)
                    mismatches.append(f"Trade {t_id} was closed on broker")

            # 2. Handle trades that exist on broker but aren't in state
            for p in broker_positions:
                t_id = p.get('tradeID')
                if t_id and t_id not in self.current_state["active_trades"]:
                    logger.info(f"Reconciliation: Found untracked trade {t_id} on broker. Importing...")
                    mismatches.append(f"Untracked trade {t_id} found on broker")

                    # Create a basic DNA for the imported trade
                    instrument = p.get('instrument', 'Unknown')
                    long_units = float(p.get('long', {}).get('units', 0))
                    short_units = float(p.get('short', {}).get('units', 0))

                    imported_dna = {
                        'instrument': instrument,
                        'units': long_units if long_units != 0 else -short_units,
                        'entry_price': p.get('long', {}).get('averagePrice', p.get('short', {}).get('averagePrice', 0)),
                        'sl': None,
                        'tp': None,
                        'ai_reasoning': "Imported from broker on startup",
                        'timestamp': datetime.utcnow().isoformat(),
                        'strategy_version': "Unknown (Imported)",
                        'is_imported': True
                    }
                    self.update_trade(t_id, imported_dna)

            if mismatches:
                return False, " | ".join(mismatches)

            return True, "Synchronized"
