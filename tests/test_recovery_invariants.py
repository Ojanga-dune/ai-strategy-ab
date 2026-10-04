import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from core.runtime_state import BotRuntimeState
from core.state_manager import StateManager
from core.notifications import NotificationManager
from core.exchange_connector import ExchangeConnector
from live_main import LiveBotOrchestrator

class TestRecoveryInvariants:
    @pytest.fixture
    def setup_bot(self):
        runtime_state = BotRuntimeState()
        state_manager = StateManager()
        notifier = MagicMock(spec=NotificationManager)
        exchange = MagicMock(spec=ExchangeConnector)
        orchestrator = LiveBotOrchestrator(runtime_state, state_manager, notifier, exchange)
        
        # Start in an outage
        runtime_state.outage_generation_id = 2
        runtime_state.recovery_notified_generation_id = 1
        runtime_state.is_outage_active = True
        runtime_state.heartbeat_pending = True
        
        return orchestrator, runtime_state, notifier, exchange

    def test_successful_completed_future_finalizes_once(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)
        
        # Mock a successful Future
        mock_future = MagicMock()
        mock_future.done.return_value = True
        mock_future.result.return_value = "SUCCESS"
        runtime_state.current_heartbeat_future = mock_future
        runtime_state.heartbeat_in_flight = True
        
        # First call: should finalize
        orchestrator.finalize_recovery(now)
        assert runtime_state.recovery_notified_generation_id == 2
        assert runtime_state.is_outage_active is False
        assert runtime_state.heartbeat_pending is False
        assert runtime_state.current_heartbeat_future is None
        assert runtime_state.heartbeat_in_flight is False
        
        # Second call: should not enter the block (current_heartbeat_future is None)
        orchestrator.finalize_recovery(now)
        # No changes, no errors
        assert runtime_state.recovery_notified_generation_id == 2
        assert runtime_state.is_outage_active is False

    def test_failed_result_future_does_not_finalize(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)
        
        # Mock a Future that completes with None (failure)
        mock_future = MagicMock()
        mock_future.done.return_value = True
        mock_future.result.return_value = None
        runtime_state.current_heartbeat_future = mock_future
        runtime_state.heartbeat_in_flight = True
        
        orchestrator.finalize_recovery(now)
        
        # Outage must remain active, generation not advanced
        assert runtime_state.is_outage_active is True
        assert runtime_state.recovery_notified_generation_id == 1
        assert runtime_state.heartbeat_pending is True

    def test_exception_future_does_not_finalize(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)
        
        # Mock a Future that raises an exception
        mock_future = MagicMock()
        mock_future.done.return_value = True
        mock_future.result.side_effect = Exception("API Error")
        runtime_state.current_heartbeat_future = mock_future
        runtime_state.heartbeat_in_flight = True
        
        orchestrator.finalize_recovery(now)
        
        # Outage must remain active
        assert runtime_state.is_outage_active is True
        assert runtime_state.recovery_notified_generation_id == 1

    def test_cancelled_future_does_not_finalize(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)
        
        # Mock a cancelled Future (usually results in an exception on .result())
        mock_future = MagicMock()
        mock_future.done.return_value = True
        mock_future.result.side_effect = Exception("Cancelled")
        runtime_state.current_heartbeat_future = mock_future
        runtime_state.heartbeat_in_flight = True
        
        orchestrator.finalize_recovery(now)
        
        assert runtime_state.is_outage_active is True
        assert runtime_state.recovery_notified_generation_id == 1

    def test_recovery_then_new_disconnect_increments_generation(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)
        
        # 1. Successful recovery
        mock_future = MagicMock()
        mock_future.done.return_value = True
        mock_future.result.return_value = "SUCCESS"
        runtime_state.current_heartbeat_future = mock_future
        runtime_state.heartbeat_in_flight = True
        
        orchestrator.finalize_recovery(now)
        assert runtime_state.recovery_notified_generation_id == 2
        assert runtime_state.is_outage_active is False
        
        # 2. New disconnect
        orchestrator._enter_outage("broker", Exception("New Fail"))
        
        # Expect: Gen 3
        assert runtime_state.outage_generation_id == 3
        assert runtime_state.recovery_notified_generation_id == 2
        assert runtime_state.is_outage_active is True

    def test_dispatch_remains_exactly_once_per_generation(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)
        
        # Mock connectivity
        notifier.state = "RUNNING"
        exchange.get_account_summary.return_value = {"equity": 1000}
        
        # Attempt recovery multiple times
        orchestrator.handle_recovery(now)
        orchestrator.handle_recovery(now)
        orchestrator.handle_recovery(now)
        
        # Should only call send_sync once because heartbeat_in_flight becomes True
        assert notifier.send_sync.call_count == 1
