import unittest
from unittest.mock import MagicMock, patch
import os
import json
import shutil
from datetime import datetime, timezone
from live_main import resolve_trade_pnl

class TestPnLResolution(unittest.TestCase):
    def setUp(self):
        self.mock_exchange = MagicMock()
        self.trade_id = "trd_12345"

    def test_resolve_pnl_success(self):
        """Verify Net PnL = realizedPL + financing."""
        self.mock_exchange.get_trade_details.return_value = {
            'realizedPL': '100.50',
            'financing': '-5.20'
        }

        pnl = resolve_trade_pnl(self.mock_exchange, self.trade_id)
        self.assertEqual(pnl, 95.30)
        self.mock_exchange.get_trade_details.assert_called_once_with(self.trade_id)

    def test_resolve_pnl_missing_details(self):
        """Verify returns None if trade details are not found."""
        self.mock_exchange.get_trade_details.return_value = None

        # Reduce retries for speed
        with patch('time.sleep', return_value=None):
            pnl = resolve_trade_pnl(self.mock_exchange, self.trade_id, retries=1)

        self.assertIsNone(pnl)

    def test_resolve_pnl_cast_error(self):
        """Verify handles non-numeric PnL fields gracefully."""
        self.mock_exchange.get_trade_details.return_value = {
            'realizedPL': 'invalid',
            'financing': '0'
        }

        with patch('time.sleep', return_value=None):
            pnl = resolve_trade_pnl(self.mock_exchange, self.trade_id, retries=1)

        self.assertIsNone(pnl)

if __name__ == "__main__":
    unittest.main()
