import unittest
from unittest.mock import MagicMock, patch
import math
from core.exchange_connector import ExchangeConnector
from core.compliance_guard import ComplianceGuard
from core.trade_tracker import TradeTracker

class TestComplianceFailClosed(unittest.TestCase):
    def setUp(self):
        self.exchange = MagicMock(spec=ExchangeConnector)
        self.compliance = ComplianceGuard()
        self.tracker = MagicMock(spec=TradeTracker)
        self.tracker.load_equity_snapshot.return_value = None

    def test_valid_equity(self):
        """Normal cycle: valid equity should be compliant."""
        equity = 10000.0
        pnl = 0.0
        is_compliant, reason = self.compliance.check_compliance(equity, pnl)
        self.assertTrue(is_compliant)
        self.assertEqual(reason, "Compliant" if self.compliance.start_of_day_equity else "Benchmark not yet set")

    def test_equity_none(self):
        """API Failure: equity is None should be non-compliant but flagged as Invalid Account State."""
        is_compliant, reason = self.compliance.check_compliance(None, 0.0)
        self.assertFalse(is_compliant)
        self.assertIn("Invalid Account State", reason)

    def test_equity_zero_or_negative(self):
        """Invalid Equity: equity <= 0 should be non-compliant and flagged as Invalid Account State."""
        for val in [0.0, -100.0]:
            is_compliant, reason = self.compliance.check_compliance(val, 0.0)
            self.assertFalse(is_compliant)
            self.assertIn("Invalid Account State", reason)

    def test_edge_case_equities(self):
        """Test NaN, Inf, and Non-numeric equity values."""
        # NaN
        is_compliant, reason = self.compliance.check_compliance(float('nan'), 0.0)
        self.assertFalse(is_compliant, "NaN equity should not be compliant")
        self.assertIn("Invalid Account State", reason)

        # Infinity
        for val in [float('inf'), float('-inf')]:
            is_compliant, reason = self.compliance.check_compliance(val, 0.0)
            if val == float('-inf'):
                self.assertFalse(is_compliant)
                self.assertIn("Invalid Account State", reason)

    def test_real_violation_drawdown(self):
        """Risk Violation: High drawdown should trigger HARD STOP."""
        self.compliance.start_of_day_equity = 10000.0
        # Drawdown = 10000 - 9700 = 300 (Limit is 150)
        is_compliant, reason = self.compliance.check_compliance(9700.0, -300.0)
        self.assertFalse(is_compliant)
        self.assertIn("HARD STOP", reason)

    def test_benchmark_persistence(self):
        """Benchmark should not be reset by invalid values."""
        # 1. Set valid benchmark
        self.compliance.update_daily_start(10000.0)
        self.assertEqual(self.compliance.start_of_day_equity, 10000.0)

        # 2. Try to update with None
        self.compliance.update_daily_start(None)
        self.assertEqual(self.compliance.start_of_day_equity, 10000.0)

        # 3. Try to update with 0
        self.compliance.update_daily_start(0.0)
        self.assertEqual(self.compliance.start_of_day_equity, 10000.0)

    def test_exchange_summary_failures(self):
        """Verify get_account_summary returns None on various failures."""
        with patch('requests.get') as mock_get:
            connector = ExchangeConnector(api_key="key", account_id="id")

            # 1. Timeout/Exception
            mock_get.side_effect = Exception("Timeout")
            self.assertIsNone(connector.get_account_summary())

            # 2. Non-200 Response
            mock_get.side_effect = None
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_get.return_value = mock_response
            self.assertIsNone(connector.get_account_summary())

    def test_missing_equity_field(self):
        """Verify handling of summary that is missing the 'equity' key."""
        with patch('requests.get') as mock_get:
            connector = ExchangeConnector(api_key="key", account_id="id")
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"account": {"balance": "1000.0"}} # No equity
            mock_get.return_value = mock_response

            summary = connector.get_account_summary()
            self.assertIsNotNone(summary)
            self.assertNotIn('equity', summary)

if __name__ == "__main__":
    unittest.main()
