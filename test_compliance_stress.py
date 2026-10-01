import os
import logging
import unittest
from unittest.mock import MagicMock, patch
from core.compliance_guard import ComplianceGuard
from core.exchange_connector import ExchangeConnector

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ComplianceStressTest")

class TestComplianceGuardStress(unittest.TestCase):
    def setUp(self):
        # Typical Prop Firm Limits - PASS AS INDIVIDUAL VALUES
        self.max_drawdown = 5000.0
        self.daily_loss = 3000.0
        self.limits = {
            "max_intraday_drawdown": self.max_drawdown,
            "daily_loss_limit": self.daily_loss,
        }
        # The ComplianceGuard constructor expects float/int, not a dict
        self.guard = ComplianceGuard(
            max_intraday_drawdown=self.max_drawdown,
            daily_loss_limit=self.daily_loss
        )
        # Mock the exchange connector
        self.mock_exchange = MagicMock(spec=ExchangeConnector)

    def test_daily_loss_limit_trigger(self):
        """Test that hitting the daily loss limit triggers non-compliance."""
        logger.info("Testing Daily Loss Limit trigger...")

        # Set a huge drawdown limit so it doesn't trigger first
        self.guard.max_intraday_drawdown = 100000

        start_equity = 100000
        self.guard.update_daily_start(start_equity)

        # Current equity is $4k below start (Daily Loss Limit is $3k)
        current_equity = 96000
        current_pnl = current_equity - start_equity

        is_compliant, reason = self.guard.check_compliance(current_equity, current_pnl)

        logger.info(f"Equity: {current_equity}, PnL: {current_pnl}, Compliant: {is_compliant}, Reason: {reason}")
        self.assertFalse(is_compliant)
        self.assertIn("Daily loss limit", reason)

    def test_intraday_drawdown_trigger(self):
        """Test that hitting the max intraday drawdown triggers non-compliance."""
        logger.info("Testing Intraday Drawdown trigger...")
        
        start_equity = 100000
        self.guard.update_daily_start(start_equity)
        
        # Simulate a drawdown: Peak equity was 100k, now it's 94k (Drop of $6k > $5k limit)
        # In a real scenario, the guard tracks the peak. 
        # For this test, we'll simulate the state.
        self.guard.peak_equity = 100000 
        current_equity = 94000
        current_pnl = current_equity - start_equity
        
        is_compliant, reason = self.guard.check_compliance(current_equity, current_pnl)

        logger.info(f"Equity: {current_equity}, PnL: {current_pnl}, Compliant: {is_compliant}, Reason: {reason}")
        self.assertFalse(is_compliant)
        self.assertIn("Intraday drawdown", reason)

    def test_recovery_within_limits(self):
        """Test that staying within limits remains compliant."""
        logger.info("Testing compliance within limits...")
        
        start_equity = 100000
        self.guard.update_daily_start(start_equity)
        
        current_equity = 98000 # $2k loss (Within both $3k and $5k limits)
        current_pnl = current_equity - start_equity
        
        is_compliant, reason = self.guard.check_compliance(current_equity, current_pnl)
        
        logger.info(f"Equity: {current_equity}, PnL: {current_pnl}, Compliant: {is_compliant}")
        self.assertTrue(is_compliant)

if __name__ == "__main__":
    unittest.main()
