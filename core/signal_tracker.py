import json
import logging
import os
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

class SignalTracker:
    """
    Tracks signals to ensure idempotency.
    Prevents the bot from re-attempting the same signal within the same candle.
    """
    def __init__(self, storage_dir: str = "data/signals"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.consumed_signals_file = self.storage_dir / "consumed_signals.json"
        self.consumed_signals = self._load_consumed_signals()

    def _load_consumed_signals(self) -> Set[str]:
        """Loads the set of consumed signal keys from disk."""
        if not self.consumed_signals_file.exists():
            return set()
        try:
            with open(self.consumed_signals_file, 'r') as f:
                return set(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load consumed signals: {e}")
            return set()

    def _save_consumed_signals(self):
        """Persists the set of consumed signal keys to disk."""
        try:
            with open(self.consumed_signals_file, 'w') as f:
                json.dump(list(self.consumed_signals), f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save consumed signals: {e}")

    def is_consumed(self, strategy_version: str, instrument: str, timestamp: float) -> bool:
        """
        Checks if a signal has already been attempted.
        Key: (strategy_version, instrument, timestamp)
        """
        signal_key = f"{strategy_version}_{instrument}_{int(timestamp)}"
        return signal_key in self.consumed_signals

    def mark_consumed(self, strategy_version: str, instrument: str, timestamp: float):
        """Marks a signal as consumed/failed to prevent re-attempts."""
        signal_key = f"{strategy_version}_{instrument}_{int(timestamp)}"
        self.consumed_signals.add(signal_key)
        self._save_consumed_signals()
        logger.info(f"Signal {signal_key} marked as consumed.")

    def clear_old_signals(self, days_to_keep: int = 7):
        """
        Optional: Clean up old signals to prevent the JSON file from growing indefinitely.
        """
        pass
