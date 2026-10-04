import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from core.runtime_state import BotRuntimeState
from core.state_manager import StateManager
from core.notifications import NotificationManager
from core.exchange_connector import ExchangeConnector
from live_main import LiveBotOrchestrator

class TestGenerationLifecycle:
    @pytest.fixture
    def setup_bot(self):
        runtime_state = BotRuntimeState()
        state_manager = StateManager()
        notifier = MagicMock(spec=NotificationManager)
        exchange = MagicMock(spec=ExchangeConnector)
        orchestrator = LiveBotOrchestrator(runtime_state, state_manager, notifier, exchange)
        
        # Initial State: 1/1
        runtime_state.outage_generation_id = 1
        runtime_state.recovery_notified_generation_id = 1
        runtime_state.is_outage_active = False
        
        return orchestrator, runtime_state, notifier, exchange

    def test_monotonic_generation_sequence(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)

        # --- Cycle 1: Trigger Outage ---
        orchestrator._enter_outage("broker", Exception("Network Fail"))
        # Expect: 2/1
        assert runtime_state.outage_generation_id == 2
        assert runtime_state.recovery_notified_generation_id == 1
        assert runtime_state.is_outage_active is True

        # --- Cycle 2: Trigger Recovery ---
        # Mock connectivity success
        notifier.state = "RUNNING"
        exchange.get_account_summary.return_value = {"equity": 1000, "balance": 1000}
        
        # Mock successful send sync (returns a completed Future)
        mock_future = MagicMock()
        mock_future.done.return_value = True
        notifier.send_sync.return_value = mock_future

        orchestrator.handle_recovery(now)
        # Recovery notification dispatched, but finalize_recovery closes the state
        orchestrator.finalize_recovery(now)
        
        # Expect: 2/2
        assert runtime_state.outage_generation_id == 2
        assert runtime_state.recovery_notified_generation_id == 2
        assert runtime_state.is_outage_active is False

        # --- Cycle 3: Trigger Outage ---
        orchestrator._enter_outage("broker", Exception("Network Fail 2"))
        # Expect: 3/2
        assert runtime_state.outage_generation_id == 3
        assert runtime_state.recovery_notified_generation_id == 2
        assert runtime_state.is_outage_active is True

        # --- Cycle 4: Trigger Recovery ---
        orchestrator.handle_recovery(now)
        orchestrator.finalize_recovery(now)
        # Expect: 3/3
        assert runtime_state.outage_generation_id == 3
        assert runtime_state.recovery_notified_generation_id == 3
        assert runtime_state.is_outage_active is False

        # --- Cycle 5: Trigger Outage ---
        orchestrator._enter_outage("broker", Exception("Network Fail 3"))
        # Expect: 4/3
        assert runtime_state.outage_generation_id == 4
        assert runtime_state.recovery_notified_generation_id == 3
        assert runtime_state.is_outage_active is True

        # --- Cycle 6: Trigger Recovery ---
        orchestrator.handle_recovery(now)
        orchestrator.finalize_recovery(now)
        # Expect: 4/4
        assert runtime_state.outage_generation_id == 4
        assert runtime_state.recovery_notified_generation_id == 4
        assert runtime_state.is_outage_active is False

    def test_idempotent_outage_errors(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        
        # Trigger first outage
        orchestrator._enter_outage("broker", Exception("First Fail"))
        gen_after_first = runtime_state.outage_generation_id # Should be 2
        
        # Trigger second error during SAME outage
        orchestrator._enter_outage("broker", Exception("Second Fail"))
        
        # Invariance: Repeated errors during a single outage must NOT increment outage_generation_id
        assert runtime_state.outage_generation_id == gen_after_first
        assert runtime_state.is_outage_active is True

    def test_failed_recovery_does_not_advance_generation(self, setup_bot):
        orchestrator, runtime_state, notifier, exchange = setup_bot
        now = datetime.now(timezone.utc)

        # Enter outage
        orchestrator._enter_outage("broker", Exception("Fail"))
        current_gen = runtime_state.outage_generation_id # 2
        
        # Attempt recovery but notification fails (send_sync returns None)
        notifier.state = "RUNNING"
        exchange.get_account_summary.return_value = {"equity": 1000, "balance": 1000}
        notifier.send_sync.return_value = None
        
        orchestrator.handle_recovery(now)
        orchestrator.finalize_recovery(now)
        
        # Should still be in outage, generation unchanged, recovery NOT notified
        assert runtime_state.is_outage_active is True
        assert runtime_state.outage_generation_id == current_gen
        assert runtime_state.recovery_notified_generation_id == 1
