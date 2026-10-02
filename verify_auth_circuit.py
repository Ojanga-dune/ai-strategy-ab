import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone, timedelta
from core.exchange_connector import ExchangeConnector

class TestAuthCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.connector = ExchangeConnector(api_key="test_key", account_id="101-12345", simulation_mode=False)
        # Mock the requests.get and requests.post to avoid actual network calls
        self.patcher_get = patch('requests.get')
        self.patcher_post = patch('requests.post')
        self.mock_get = self.patcher_get.start()
        self.mock_post = self.patcher_post.start()

    def tearDown(self):
        self.patcher_get.stop()
        self.patcher_post.stop()

    def test_A_normal_authenticated_request(self):
        """Normal request updates status to CONNECTED."""
        self.mock_get.return_value.status_code = 200
        self.mock_get.return_value.json.return_value = {"account": {"NAV": "1000", "balance": "1000", "id": "101-12345", "currency": "USD"}}
        
        res = self.connector.get_account_summary()
        self.assertEqual(self.connector.connection_status, "CONNECTED")
        self.assertIsNotNone(res)

    def test_B_first_401_auth_failed(self):
        """First 401 transition to AUTH_FAILED and logs critical."""
        self.mock_get.return_value.status_code = 401
        self.mock_get.return_value.text = "Unauthorized"
        
        res = self.connector.get_account_summary()
        self.assertEqual(self.connector.connection_status, "AUTH_FAILED")
        self.assertEqual(self.connector.auth_failure_reason, "401 Unauthorized")
        self.assertIsNotNone(self.connector.auth_failed_since)
        self.assertIsNone(res)

    def test_C_repeated_401_no_spam(self):
        """Repeated 401s do not reset _auth_failure_logged."""
        self.mock_get.return_value.status_code = 401
        self.connector.get_account_summary() # First failure
        self.assertTrue(self.connector._auth_failure_logged)
        
        # Second failure - should not log critical again (verified via logs in real run, here we check state)
        self.connector.get_account_summary()
        self.assertTrue(self.connector._auth_failure_logged)
        self.assertEqual(self.connector.connection_status, "AUTH_FAILED")

    def test_D_trading_write_blocked(self):
        """Writes are blocked during AUTH_FAILED."""
        self.connector.connection_status = "AUTH_FAILED"
        self.connector.auth_failure_reason = "401 Unauthorized"
        
        res = self.connector.place_market_order("XAU_USD", 0.1)
        self.assertEqual(res['status'], 'error')
        self.assertIn("blocked", res['message'])
        self.mock_post.assert_not_called()

    def test_E_read_request_distinguishable(self):
        """AUTH_FAILED reads return empty but log the reason."""
        self.connector.connection_status = "AUTH_FAILED"
        self.connector.auth_failure_reason = "401 Unauthorized"
        
        df = self.connector.get_latest_candles("XAU_USD", "H1")
        self.assertTrue(df.empty)
        # In a real test we'd check logs, here we verify it didn't call the API
        self.mock_get.assert_not_called()

    def test_F_recovery_probe_succeeds(self):
        """Probe succeeds and moves state to CONNECTED after full verification."""
        self.connector.connection_status = "AUTH_FAILED"
        
        # 1. Mock Auth Probe Success
        self.mock_get.return_value.status_code = 200
        self.mock_get.return_value.json.return_value = {"account": {"NAV": "1000", "balance": "1000"}}
        
        # 2. Mock State Manager for reconciliation
        mock_sm = MagicMock()
        mock_sm.reconcile_with_broker.return_value = (True, "Synchronized")
        
        # Set probe time to now
        self.connector.next_auth_probe_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        
        # Execute recovery
        self.connector.handle_auth_recovery(state_manager=mock_sm)
        
        # Should be CONNECTED now
        self.assertEqual(self.connector.connection_status, "CONNECTED")
        # Verify the probe and account summary were actually called (bypassing guard)
        # get_open_positions and get_account_summary should have been called via bypass_guard=True
        self.assertTrue(self.mock_get.called)

    def test_G_reconciliation_fails_stay_closed(self):
        """Recovery probe succeeds but reconciliation fails -> stay AUTH_FAILED."""
        self.connector.connection_status = "AUTH_FAILED"
        self.mock_get.return_value.status_code = 200
        self.mock_get.return_value.json.return_value = {"account": {"NAV": "1000", "balance": "1000"}}
        
        mock_sm = MagicMock()
        mock_sm.reconcile_with_broker.return_value = (False, "mismatch")
        
        self.connector.next_auth_probe_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.connector.handle_auth_recovery(state_manager=mock_sm)
        self.assertEqual(self.connector.connection_status, "AUTH_FAILED")

    def test_H_auth_failure_logged_resets(self):
        """Successful recovery resets the auth failure log flag."""
        self.connector.connection_status = "AUTH_FAILED"
        self.connector._auth_failure_logged = True
        self.mock_get.return_value.status_code = 200
        self.mock_get.return_value.json.return_value = {"account": {"NAV": "1000", "balance": "1000"}}
        
        mock_sm = MagicMock()
        mock_sm.reconcile_with_broker.return_value = (True, "Synchronized")
        
        self.connector.next_auth_probe_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.connector.handle_auth_recovery(state_manager=mock_sm)
        self.assertFalse(self.connector._auth_failure_logged)

    def test_I_new_incident_logged(self):
        """After recovery, a new 401 is logged as a new incident."""
        self.connector.connection_status = "CONNECTED"
        self.connector._auth_failure_logged = False
        
        self.mock_get.return_value.status_code = 401
        self.connector.get_account_summary()
        self.assertEqual(self.connector.connection_status, "AUTH_FAILED")
        self.assertTrue(self.connector._auth_failure_logged)

    def test_J_403_preserves_forbidden(self):
        """403 transition preserves FORBIDDEN reason."""
        self.mock_get.return_value.status_code = 403
        self.connector.get_account_summary()
        self.assertEqual(self.connector.connection_status, "AUTH_FAILED")
        self.assertEqual(self.connector.auth_failure_reason, "403 Forbidden")

    def test_K_504_remains_degraded(self):
        """504 server error stays DEGRADED/DISCONNECTED, not AUTH_FAILED."""
        self.mock_get.return_value.status_code = 504
        self.connector.get_account_summary()
        self.assertNotEqual(self.connector.connection_status, "AUTH_FAILED")
        self.assertIn(self.connector.connection_status, ["DEGRADED", "DISCONNECTED"])

if __name__ == "__main__":
    # Need to import MagicMock here since it's used in tests
    from unittest.mock import MagicMock
    unittest.main()
