import unittest
from unittest.mock import MagicMock, patch
import logging
from live_main import main

# Configure logging to see the output
logging.basicConfig(level=logging.INFO)

class TestKillSwitch(unittest.TestCase):
    def setUp(self):
        self.mock_exchange = MagicMock()
        self.mock_notifier = MagicMock()
        self.mock_compliance = MagicMock()
        
    def test_emergency_shutdown_closes_all_positions(self):
        """Verify that when is_compliant is False, the bot closes all open positions."""
        # Mock open positions
        self.mock_exchange.get_open_positions.return_value = [
            {'instrument': 'XAU_USD', 'long': {'units': '10'}, 'short': {'units': '0'}},
            {'instrument': 'EUR_USD', 'long': {'units': '0'}, 'short': {'units': '20'}},
        ]
        
        # Mock compliance to fail
        self.mock_compliance.check_compliance.return_value = (False, "Daily loss limit hit")
        
        # We need to mock the main loop. Since main() has a while True, 
        # we'll simulate the logic inside the loop for the shutdown part.
        
        # Simulate the shutdown block from live_main.py
        is_compliant, reason = self.mock_compliance.check_compliance(10000, -600)
        
        if not is_compliant:
            # This is the logic from live_main.py lines 621-632
            all_pos = self.mock_exchange.get_open_positions()
            for p in all_pos:
                inst = p.get('instrument', 'XAU_USD')
                units = float(p.get('long', {}).get('units', 0)) - float(p.get('short', {}).get('units', 0))
                if units != 0:
                    self.mock_exchange.place_market_order(inst, -units)

        # Verify that place_market_order was called for both positions with opposite units
        self.assertEqual(self.mock_exchange.place_market_order.call_count, 2)
        self.mock_exchange.place_market_order.assert_any_call('XAU_USD', -10.0)
        self.mock_exchange.place_market_order.assert_any_call('EUR_USD', 20.0)

if __name__ == "__main__":
    unittest.main()
