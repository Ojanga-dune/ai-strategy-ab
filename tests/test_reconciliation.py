import unittest
from unittest.mock import MagicMock
import os
import json
from pathlib import Path
from core.state_manager import StateManager

class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.state_file = "data/test_state.json"
        self.manager = StateManager(state_file=self.state_file)

    def tearDown(self):
        if os.path.exists(self.state_file):
            os.remove(self.state_file)

    def test_sync_success(self):
        """Verify that identical state and broker positions return True."""
        # Setup state
        self.manager.update_trade("trd_1", {"instrument": "XAU_USD"})
        
        # Mock broker positions
        broker_pos = [{'tradeID': 'trd_1', 'instrument': 'XAU_USD'}]
        
        synced, msg = self.manager.reconcile_with_broker(broker_pos)
        self.assertTrue(synced)
        self.assertEqual(msg, "Synchronized")

    def test_mismatch_untracked_trade(self):
        """Verify that a trade on broker but not in state triggers a mismatch alert."""
        # State is empty
        broker_pos = [{'tradeID': 'trd_untracked', 'instrument': 'XAU_USD', 'long': {'units': '1'}, 'short': {'units': '0'}}]
        
        synced, msg = self.manager.reconcile_with_broker(broker_pos)
        self.assertFalse(synced)
        self.assertIn("Untracked trade trd_untracked found on broker", msg)
        self.assertIn("trd_untracked", self.manager.current_state["active_trades"])

    def test_mismatch_closed_on_broker(self):
        """Verify that a trade in state but not on broker triggers a mismatch alert."""
        # Setup state
        self.manager.update_trade("trd_closed", {"instrument": "XAU_USD"})
        
        # Broker is empty
        broker_pos = []
        
        synced, msg = self.manager.reconcile_with_broker(broker_pos)
        self.assertFalse(synced)
        self.assertIn("Trade trd_closed was closed on broker", msg)
        self.assertNotIn("trd_closed", self.manager.current_state["active_trades"])

if __name__ == "__main__":
    unittest.main()
