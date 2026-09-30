import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
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
        self.current_state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Loads the state from disk on startup."""
        if not self.state_path.exists():
            return {"active_trades": {}, "last_cycle_timestamp": None, "session_start_equity": None}

        try:
            with open(self.state_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state file: {e}")
            return {"active_trades": {}, "last_cycle_timestamp": None, "session_start_equity": None}

    def save_state(self):
        """Persists current state to disk."""
        try:
            with open(self.state_path, 'w') as f:
                json.dump(self.current_state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def update_trade(self, trade_id: str, data: Dict[str, Any]):
        """Updates or adds a trade to the active state."""
        self.current_state["active_trades"][trade_id] = data
        self.save_state()

    def remove_trade(self, trade_id: str):
        """Removes a trade from active state upon closure."""
        if trade_id in self.current_state["active_trades"]:
            del self.current_state["active_trades"][trade_id]
            self.save_state()

    def set_session_equity(self, equity: float):
        """Records the equity at the start of a session."""
        self.current_state["session_start_equity"] = equity
        self.save_state()

    def reconcile_with_broker(self, broker_positions: List[Dict[str, Any]]):
        """
        Reconciles the internal state with actual broker positions.
        - Trades in state but NOT in broker -> Mark as CLOSED.
        - Trades in broker but NOT in state -> Add to state as 'IMPORTED'.
        """
        broker_trade_ids = [p.get('tradeID') for p in broker_positions if p.get('tradeID')]
        state_trade_ids = list(self.current_state["active_trades"].keys())

        # 1. Handle trades that were closed on broker but are still in state
        for t_id in state_trade_ids:
            if t_id not in broker_trade_ids:
                logger.info(f"Reconciliation: Trade {t_id} closed on broker. Removing from active state.")
                self.remove_trade(t_id)

        # 2. Handle trades that exist on broker but aren't in state
        for p in broker_positions:
            t_id = p.get('tradeID')
            if t_id and t_id not in self.current_state["active_trades"]:
                logger.info(f"Reconciliation: Found untracked trade {t_id} on broker. Importing...")

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
