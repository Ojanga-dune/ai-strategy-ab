import logging
import json
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """
    Prevents continuous failure loops.
    Halts trading after N consecutive rejections.
    """
    def __init__(self, threshold: int = 5, storage_file: str = "data/circuit_breaker.json"):
        self.threshold = threshold
        self.storage_path = Path(storage_file)
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if not self.storage_path.exists():
            return {"consecutive_rejections": 0, "tripped": False}
        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load circuit breaker state: {e}")
            return {"consecutive_rejections": 0, "tripped": False}

    def _save_state(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save circuit breaker state: {e}")

    def record_rejection(self) -> Tuple[bool, str]:
        """
        Increments rejection count. 
        Returns (is_tripped, reason).
        """
        self.state["consecutive_rejections"] += 1
        if self.state["consecutive_rejections"] >= self.threshold:
            self.state["tripped"] = True
            self._save_state()
            return True, f"CIRCUIT BREAKER TRIPPED: {self.state['consecutive_rejections']} consecutive rejections."
        
        self._save_state()
        return False, ""

    def record_success(self):
        """Resets the counter on a successful fill."""
        if self.state["consecutive_rejections"] > 0:
            self.state["consecutive_rejections"] = 0
            self.state["tripped"] = False
            self._save_state()

    def is_tripped(self) -> bool:
        return self.state.get("tripped", False)

    def reset(self):
        """Manual reset of the circuit breaker."""
        self.state = {"consecutive_rejections": 0, "tripped": False}
        self._save_state()
