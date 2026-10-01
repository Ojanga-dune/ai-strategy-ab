import unittest
from unittest.mock import MagicMock, patch
import os
import json
import shutil
from datetime import datetime, timezone
from live_main import run_live_cycle, monitor_trade_outcomes

class TestIDAlignment(unittest.TestCase):
    def setUp(self):
        self.instrument = "XAU_USD"
        self.granularity = "H1"
        self.test_dir = "data/trades_test"

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

        # Ensure idempotency and duplicate checks always pass for these tests
        self.mock_signal_tracker.is_consumed.return_value = False
        self.mock_exchange.check_order_exists.return_value = False

        # Setup TradeTracker with a test directory
        from core.trade_tracker import TradeTracker
        self.tracker = TradeTracker(storage_dir=self.test_dir)

        # Default mocks to allow the cycle to reach execution
        self.mock_session_filter.is_trade_allowed.return_value = (True, "")
        self.mock_news_guard.is_news_event_active.return_value = (False, "")
        self.mock_candle_guard.is_candle_closed.return_value = True

        import pandas as pd
        self.df = pd.DataFrame({'close': [2000.0], 'ATR': [2.0]}, index=[datetime.now(timezone.utc)])
        self.mock_exchange.get_latest_candles.return_value = self.df
        self.mock_exchange.get_mtf_candles.return_value = {'H1': self.df}
        self.mock_exchange.get_account_summary.return_value = {'balance': 10000, 'equity': 10000}
        self.mock_exchange.get_open_positions.return_value = []

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

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_id_separation_and_storage(self):
        """Verify that order_id and trade_id are separated and stored with a stable local_id."""
        order_id = "ord_12345"
        trade_id = "trd_67890"

        # Mock OANDA response with both IDs
        self.mock_exchange.place_market_order.return_value = {
            'status': 'success',
            'orderCreateTransaction': {'id': order_id},
            'orderFillTransaction': {
                'tradeOpened': {'tradeID': trade_id}
            }
        }

        # Use a unique timestamp for the signal
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
            self.mock_notifier, self.tracker, self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker
        )

        # Verify a file was created in the test directory
        files = os.listdir(self.test_dir)
        self.assertEqual(len(files), 1, f"Expected 1 trade file, found {len(files)}")

        filename = files[0]
        self.assertFalse(filename.startswith(order_id), "Filename should not be just the order_id")
        self.assertFalse(filename.startswith(trade_id), "Filename should not be just the trade_id")
        self.assertTrue(filename.startswith("trade_"), "Filename should start with 'trade_'")

        # Verify content of the file
        with open(os.path.join(self.test_dir, filename), 'r') as f:
            data = json.load(f)

        self.assertEqual(data['order_id'], order_id, "order_id mismatch in stored DNA")
        self.assertEqual(data['trade_id'], trade_id, "trade_id mismatch in stored DNA")
        self.assertEqual(data['status'], 'OPEN')

    def test_outcome_update_uses_local_id(self):
        """Verify that update_outcome uses the local_id but API calls use trade_id."""
        order_id = "ord_123"
        trade_id = "trd_456"
        local_id = f"trade_test_{order_id}"

        # Manually record a trade
        trade_dna = {
            'order_id': order_id,
            'trade_id': trade_id,
            'instrument': self.instrument,
            'entry_price': 2000.0,
            'units': 0.1,
            'sl': 1990.0,
            'tp': 2010.0,
            'strategy_version': 'v1'
        }
        self.tracker.record_entry(local_id, trade_dna)

        # Mock broker to show the trade has closed (empty positions)
        self.mock_exchange.get_open_positions.return_value = []
        self.mock_exchange.get_latest_candles.return_value = self.df

        # Mock place_market_order to return a failure so it doesn't create new trades
        self.mock_exchange.place_market_order.return_value = {'status': 'error', 'error_code': 400}

        # Mock PnL resolution to use trade_id
        self.mock_exchange.get_trade_details.return_value = {'realizedPL': 10.0, 'financing': 1.0}

        # Manually trigger the outcome monitoring logic
        monitored_assets = [{"symbol": self.instrument, "gran": self.granularity}]
        monitor_trade_outcomes(
            self.mock_exchange, self.tracker, self.mock_notifier,
            self.mock_registry, monitored_assets
        )

        # Verify the API was called with the trade_id
        self.mock_exchange.get_trade_details.assert_called_with(trade_id)

        # Verify the file was updated using the local_id
        with open(os.path.join(self.test_dir, f"{local_id}.json"), 'r') as f:
            data = json.load(f)
        self.assertEqual(data['status'], 'CLOSED')
        self.assertEqual(data['pnl'], 11.0)

    def test_missing_fill_transaction_handles_gracefully(self):
        """Verify that if orderFillTransaction is missing, trade_id remains None and system doesn't crash."""
        order_id = "ord_999"

        # Mock OANDA response with orderCreateTransaction but NO orderFillTransaction
        self.mock_exchange.place_market_order.return_value = {
            'status': 'success',
            'orderCreateTransaction': {'id': order_id},
            # 'orderFillTransaction' is intentionally missing
        }

        # Use a unique timestamp for the signal
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
            self.mock_notifier, self.tracker, self.mock_registry,
            self.mock_session_filter, self.mock_candle_guard, self.mock_news_guard,
            self.mock_signal_tracker, self.mock_circuit_breaker
        )

        # Verify a record was still created (using order_id as fallback for local_id)
        files = os.listdir(self.test_dir)
        self.assertTrue(len(files) > 0, "A trade file should still be created even if fill is missing")

        # Verify the trade_id in the file is None
        filename = [f for f in files if "ord_999" in f][0]
        with open(os.path.join(self.test_dir, filename), 'r') as f:
            data = json.load(f)
        self.assertIsNone(data.get('trade_id'), "trade_id should be None if orderFillTransaction was missing")

if __name__ == "__main__":
    unittest.main()
