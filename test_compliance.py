import unittest
from unittest.mock import MagicMock, patch
from core.compliance_guard import ComplianceGuard
from core.exchange_connector import ExchangeConnector

class TestComplianceGuard(unittest.TestCase):
    def setUp(self):
        self.guard = ComplianceGuard(
            max_intraday_drawdown=100.0,
            daily_loss_limit=200.0
        )

    def test_compliant_state(self):
        """Test that bot remains compliant under normal conditions."""
        self.guard.update_daily_start(10000.0)
        # Equity 9950, PnL -50 (within limits)
        is_compliant, reason = self.guard.check_compliance(9950.0, -50.0)
        self.assertTrue(is_compliant)
        self.assertEqual(reason, "Compliant")

    def test_intraday_drawdown_violation(self):
        """Test that exceeding max_intraday_drawdown triggers shutdown."""
        self.guard.update_daily_start(10000.0)
        # Equity 9890 (Drawdown = 110, Limit = 100)
        is_compliant, reason = self.guard.check_compliance(9890.0, -110.0)
        self.assertFalse(is_compliant)
        self.assertIn("HARD STOP: Intraday drawdown", reason)
        self.assertTrue(self.guard.kill_switch_active)

    def test_daily_loss_limit_violation(self):
        """Test that exceeding daily_loss_limit triggers shutdown."""
        self.guard.update_daily_start(10000.0)
        # PnL -210 (Limit = 200)
        is_compliant, reason = self.guard.check_compliance(9790.0, -210.0)
        self.assertFalse(is_compliant)
        self.assertIn("HARD STOP: Daily loss limit", reason)
        self.assertTrue(self.guard.kill_switch_active)

    def test_kill_switch_persistence(self):
        """Test that once kill switch is active, it stays active."""
        self.guard.update_daily_start(10000.0)
        self.guard.check_compliance(9000.0, -1000.0) # Trigger

        # Try to check again with recovered equity
        is_compliant, reason = self.guard.check_compliance(10000.0, 0.0)
        self.assertFalse(is_compliant)
        self.assertIn("Kill switch is already active", reason)

if __name__ == "__main__":
    unittest.main()
