import unittest
from unittest.mock import MagicMock, patch
import time
from datetime import datetime, timezone

# We must mock the dependencies before importing live_main if it does top-level instantiation,
# but since we are testing the logic within the loop, we will mock the objects passed to run_live_cycle.

from live_main import run_live_cycle

class TestOrderRetry(unittest.TestCase):
    def setUp(self):
        self.instrument = "XAU_USD"
        self.granularity = "H1"
        self.mock_exchange = MagicMock()
        self.mock_engine = MagicMock()
        self.mock_reviewer = MagicMock()
        self.mock_risk_manager = MagicMock()
        self.mock_datalake = MagicMock()
        self.mock_notifier = MagicMock()
        self.mock_tracker = MagicMock()
        self.mock_registry = MagicMock()
        self.mock_session_filter = MagicMock()
        self.mock_candle_guard = MagicMock()
        self.mock_news_guard = MagicMock()
        self.mock_signal_tracker = MagicMock()
        self.mock_circuit_breaker = MagicMock()

        # Ensure idempotency and duplicate checks always pass
        self.mock_signal_tracker.is_consumed.return_value = False
        self.mock_exchange.check_order_exists.return_value = False
        self.mock_circuit_breaker.record_rejection.return_value = (False, "")

        # Default mocks to allow the cycle to reach execution
        self.mock_session_filter.is_trade_allowed.return_value = (True, "")
        self.mock_news_guard.is_news_event_active.return_value = (False, "")
        self.mock_candle_guard.is_candle_closed.return_value = True

        # Mock dataframes
        import pandas as pd
        self.df = pd.DataFrame({'close': [2000.0], 'ATR': [2.0]}, index=[datetime.now(timezone.utc)])
        self.mock_exchange.get_latest_candles.return_value = self.df
        self.mock_exchange.get_mtf_candles.return_value = {'H1': self.df}
        self.mock_exchange.get_account_summary.return_value = {'balance': 10000, 'equity': 10000}
        self.mock_exchange.get_open_positions.return_value = []

        # Mock strategy as champion
        self.mock_registry.get_all_strategies.return_value = [{
            'version': 'v1',
            'rules': {},
            'is_champion': True
        }]

        # Use a unique timestamp for each test signal to avoid SignalTracker duplicate block
        now = datetime.now(timezone.utc)
        self.mock_engine.find_candidates.return_value = [{'timestamp': now, 'price': 2000.0}]
        self.mock_reviewer.validate_signals.return_value = [{
            'timestamp': now,
            'price': 2000.0,
            'ai_reasoning': 'bullish signal'
        }]

        self.mock_risk_manager.can_trade.return_value = (True, "")
        self.mock_risk_manager.calculate_position_size.return_value = 0.1

    def test_retry_on_500_then_success(self):
        """Test that a 500 error triggers a retry and eventually succeeds."""
        # 1st call: 500 Error, 2nd call: Success
        self.mock_exchange.place_market_order.side_effect = [
            {'status': 'error', 'error_code': 500, 'message': 'Internal Server Error'},
            {'status': 'success', 'orderFillTransaction': {'id': 'fill123'}, 'orderCreateTransaction': {'id': 'ord123'}}
        ]

        run_live_cycle(
            self.instrument, self.granularity, self.mock_exchange, self.mock_engine,
            self.mock_reviewer, self.mock_risk_manager, self.mock_datalake,
            self.mock_notifier, self.mock_tracker, self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker
        )

        self.assertEqual(self.mock_exchange.place_market_order.call_count, 2)
        self.mock_tracker.record_entry.assert_called_once()

    def test_no_retry_on_400(self):
        """Test that a 400 error does NOT trigger a retry."""
        self.mock_exchange.place_market_order.return_value = {
            'status': 'error', 'error_code': 400, 'message': 'Invalid Request'
        }

        run_live_cycle(
            self.instrument, self.granularity, self.mock_exchange, self.mock_engine,
            self.mock_reviewer, self.mock_risk_manager, self.mock_datalake,
            self.mock_notifier, self.mock_tracker, self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker
        )

        self.assertEqual(self.mock_exchange.place_market_order.call_count, 1)
        # Should record as REJECTED
        args, _ = self.mock_tracker.record_entry.call_args
        self.assertEqual(args[1]['status'], 'REJECTED')

    def test_max_retries_exceeded(self):
        """Test that after 3 failures, it stops and alerts."""
        self.mock_exchange.place_market_order.return_value = {
            'status': 'error', 'error_code': 503, 'message': 'Service Unavailable'
        }

        run_live_cycle(
            self.instrument, self.granularity, self.mock_exchange, self.mock_engine,
            self.mock_reviewer, self.mock_risk_manager, self.mock_datalake,
            self.mock_notifier, self.mock_tracker, self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker
        )

        self.assertEqual(self.mock_exchange.place_market_order.call_count, 3)
        self.mock_notifier.send_sync.assert_called()

    def test_retry_on_429_rate_limit(self):
        """Verify that HTTP 429 (Too Many Requests) triggers a retry."""
        # 1st call: 429 Error, 2nd call: Success
        self.mock_exchange.place_market_order.side_effect = [
            {'status': 'error', 'error_code': 429, 'message': 'Too Many Requests'},
            {'status': 'success', 'orderFillTransaction': {'id': 'fill429'}, 'orderCreateTransaction': {'id': 'ord429'}}
        ]

        run_live_cycle(
            self.instrument, self.granularity, self.mock_exchange, self.mock_engine,
            self.mock_reviewer, self.mock_risk_manager, self.mock_datalake,
            self.mock_notifier, self.mock_tracker, self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker
        )

        self.assertEqual(self.mock_exchange.place_market_order.call_count, 2)
        self.mock_tracker.record_entry.assert_called_once()

    def test_retry_on_502_bad_gateway(self):
        """Verify that HTTP 502 (Bad Gateway) triggers a retry."""
        # 1st call: 502 Error, 2nd call: Success
        self.mock_exchange.place_market_order.side_effect = [
            {'status': 'error', 'error_code': 502, 'message': 'Bad Gateway'},
            {'status': 'success', 'orderFillTransaction': {'id': 'fill502'}, 'orderCreateTransaction': {'id': 'ord502'}}
        ]

        run_live_cycle(
            self.instrument, self.granularity, self.mock_exchange, self.mock_engine,
            self.mock_reviewer, self.mock_risk_manager, self.mock_datalake,
            self.mock_notifier, self.mock_tracker, self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker
        )

        self.assertEqual(self.mock_exchange.place_market_order.call_count, 2)
        self.mock_tracker.record_entry.assert_called_once()

if __name__ == "__main__":
    unittest.main()
