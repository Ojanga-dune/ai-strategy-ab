import unittest
from unittest.mock import MagicMock
from core.risk_manager import RiskManager

class TestDailyPnL(unittest.TestCase):
    def setUp(self):
        self.risk_manager = RiskManager()
        self.mock_exchange = MagicMock()

    def test_calculate_account_daily_pnl_success(self):
        """Test that PnL is summed correctly across different transaction types."""
        # Mock data: 2 fills (one profitable, one loss), 1 reject, 1 cancel
        self.mock_exchange.get_account_transactions.return_value = [
            {
                "id": "tx1",
                "type": "ORDER_FILL",
                "realizedPL": "100.00",
                "financing": "2.50",
                "commission": "-1.00"
            },
            {
                "id": "tx2",
                "type": "ORDER_FILL",
                "realizedPL": "-50.00",
                "financing": "1.00",
                "commission": "-1.00"
            },
            {
                "id": "tx3",
                "type": "MARKET_ORDER_REJECT",
            },
            {
                "id": "tx4",
                "type": "ORDER_CANCEL",
            }
        ]

        # Expected PnL: (100 + 2.5 - 1) + (-50 + 1 - 1) = 101.5 - 50 = 51.5
        result = self.risk_manager.calculate_account_daily_pnl(self.mock_exchange, "2023-01-01T00:00:00Z")

        self.assertEqual(result["total_pnl"], 51.5)
        self.assertEqual(result["verified_trades"], 2)
        self.assertEqual(result["rejected_orders"], 2)

    def test_calculate_account_daily_pnl_malformed_data(self):
        """Test robustness against missing or malformed PnL fields."""
        self.mock_exchange.get_account_transactions.return_value = [
            {
                "id": "tx1",
                "type": "ORDER_FILL",
                "realizedPL": "invalid", # Should be caught by try-except
                "financing": "1.00",
            },
            {
                "id": "tx2",
                "type": "ORDER_FILL",
                "realizedPL": "10.00",
                # financing and commission missing
            }
        ]

        # Expected PnL: tx1 fails (0), tx2 (10 + 0 + 0) = 10.0
        result = self.risk_manager.calculate_account_daily_pnl(self.mock_exchange, "2023-01-01T00:00:00Z")

        self.assertEqual(result["total_pnl"], 10.0)
        self.assertEqual(result["verified_trades"], 1) # Only tx2 should count if tx1 fails parsing

if __name__ == "__main__":
    unittest.main()
