import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from live_main import run_live_cycle

class TestPositionCap(unittest.TestCase):
    def setUp(self):
        self.instrument = "XAU_USD"
        self.granularity = "H1"

        # Mock dependencies
        self.mock_exchange = MagicMock()
        self.mock_engine = MagicMock()
        self.mock_reviewer = MagicMock()
        self.mock_risk_manager = MagicMock()
        self.mock_datalake = MagicMock()
        self.mock_notifier = MagicMock()
        self.mock_registry = MagicMock()
        self.mock_session_filter = MagicMock()
        self.mock_candle_guard = MagicMock()
        self.mock_news_guard = MagicMock()
        self.mock_signal_tracker = MagicMock()
        self.mock_circuit_breaker = MagicMock()

        # Ensure idempotency and duplicate checks always pass
        self.mock_signal_tracker.is_consumed.return_value = False
        self.mock_exchange.check_order_exists.return_value = False

        # Default mocks to allow the cycle to reach execution
        self.mock_session_filter.is_trade_allowed.return_value = (True, "")
        self.mock_news_guard.is_news_event_active.return_value = (False, "")
        self.mock_candle_guard.is_candle_closed.return_value = True

        import pandas as pd
        self.df = pd.DataFrame({'close': [2000.0], 'ATR': [2.0]}, index=[datetime.now(timezone.utc)])
        self.mock_exchange.get_latest_candles.return_value = self.df
        self.mock_exchange.get_mtf_candles.return_value = {'H1': self.df}
        self.mock_exchange.get_account_summary.return_value = {'balance': 10000, 'equity': 10000}

        self.mock_registry.get_all_strategies.return_value = [{
            'version': 'v1',
            'rules': {},
            'is_champion': True
        }]

        self.mock_engine.find_candidates.return_value = [{'timestamp': datetime.now(timezone.utc), 'price': 2000.0}]
        self.mock_engine.evaluate_confluence.return_value = {'regime_filter_passed': True}
        self.mock_reviewer.validate_signals.return_value = [{
            'timestamp': datetime.now(timezone.utc),
            'price': 2000.0,
            'ai_reasoning': 'bullish signal'
        }]

        self.mock_risk_manager.can_trade.return_value = (True, "")
        self.mock_risk_manager.calculate_position_size.return_value = 0.1

    def test_trade_allowed_under_cap(self):
        """Verify trade proceeds when open positions are below the cap."""
        # Mock 0 open positions (Cap is 1)
        self.mock_exchange.get_open_positions.return_value = []

        # Use a unique timestamp for the signal to avoid SignalTracker block
        now = datetime.now(timezone.utc)
        self.mock_engine.find_candidates.return_value = [{'timestamp': now, 'price': 2000.0}]
        self.mock_reviewer.validate_signals.return_value = [{
            'timestamp': now,
            'price': 2000.0,
            'ai_reasoning': 'bullish signal'
        }]

        run_live_cycle(
            self.instrument, self.granularity, self.mock_exchange, self.mock_engine,
            self.mock_reviewer, self.mock_risk_manager, self.mock_datalake,
            self.mock_notifier, MagicMock(), self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker,
            MagicMock()
        )

        # Verify that place_market_order was called
        self.assertTrue(self.mock_exchange.place_market_order.called)

    def test_trade_blocked_at_cap(self):
        """Verify trade is blocked when open positions reach the cap."""
        # Mock 1 open position (Cap is 1)
        self.mock_exchange.get_open_positions.return_value = [{'tradeID': 'trd_123'}]

        # Ensure the signal is not already consumed
        self.mock_registry.get_all_strategies.return_value = [{
            'version': 'v1',
            'rules': {},
            'is_champion': True
        }]

        run_live_cycle(
            self.instrument, self.granularity, self.mock_exchange, self.mock_engine,
            self.mock_reviewer, self.mock_risk_manager, self.mock_datalake,
            self.mock_notifier, MagicMock(), self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker,
            MagicMock()
        )

        # Verify that place_market_order was NOT called
        self.assertFalse(self.mock_exchange.place_market_order.called)

if __name__ == "__main__":
    unittest.main()
