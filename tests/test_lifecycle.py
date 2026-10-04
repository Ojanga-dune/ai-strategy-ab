import pytest
import asyncio
import threading
import time
import os
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta
from concurrent.futures import Future
from typing import List, Dict, Any

from core.notifications import NotificationManager
from core.runtime_state import BotRuntimeState
from core.state_manager import StateManager
from core.exchange_connector import ExchangeConnector
from core.strategy_registry import StrategyRegistry
from live_main import LiveBotOrchestrator

# --- Mocks ---
class MockExchange:
    def __init__(self):
        self.connection_status = "CONNECTED"
        self.api_key = "test_key"
        self.account_id = "101-test"

    def get_account_summary(self, bypass_guard=False):
        return {"equity": 10000, "balance": 10000}

    def get_open_positions(self, instrument=None, bypass_guard=False):
        return []

    def place_market_order(self, instrument, lots, **kwargs):
        return {"status": "success", "orderCreateTransaction": {"id": "test_order"}}

    def handle_auth_recovery(self, state_manager):
        pass

# --- Outage and Resilience Tests ---

def test_monotonic_outage_lifecycle():
    """
    Verifies the exact sequence of outage generation increments across 3 cycles.
    Baseline: 1/1
    Outage #2 -> 2/1
    Recovery #2 -> 2/2
    Outage #3 -> 3/2
    Recovery #3 -> 3/3
    Outage #4 -> 4/3
    Recovery #4 -> 4/4
    """
    runtime = BotRuntimeState()
    # Force baseline to 1/1
    runtime.outage_generation_id = 1
    runtime.recovery_notified_generation_id = 1

    sm = StateManager(state_file="data/test_lifecycle.json")
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    def do_recovery():
        # Mock verified health
        notifier.state = "RUNNING"
        with patch.object(exchange, 'get_account_summary', return_value={"equity": 100}):
            # Mock successful notification delivery
            mock_future = Future()
            mock_future.set_result(True)
            with patch.object(notifier, 'send_sync', return_value=mock_future):
                orch.handle_recovery(datetime.now(timezone.utc))
                orch.finalize_recovery(datetime.now(timezone.utc))

    # Cycle 1: Outage #2
    orch._enter_outage("broker", Exception("Fail 1"))
    assert runtime.outage_generation_id == 2
    assert runtime.recovery_notified_generation_id == 1
    assert runtime.is_outage_active is True

    # Recovery #2
    do_recovery()
    assert runtime.outage_generation_id == 2
    assert runtime.recovery_notified_generation_id == 2
    assert runtime.is_outage_active is False

    # Cycle 2: Outage #3
    orch._enter_outage("broker", Exception("Fail 2"))
    assert runtime.outage_generation_id == 3
    assert runtime.recovery_notified_generation_id == 2
    assert runtime.is_outage_active is True

    # Recovery #3
    do_recovery()
    assert runtime.outage_generation_id == 3
    assert runtime.recovery_notified_generation_id == 3
    assert runtime.is_outage_active is False

    # Cycle 3: Outage #4
    orch._enter_outage("broker", Exception("Fail 3"))
    assert runtime.outage_generation_id == 4
    assert runtime.recovery_notified_generation_id == 3
    assert runtime.is_outage_active is True

    # Recovery #4
    do_recovery()
    assert runtime.outage_generation_id == 4
    assert runtime.recovery_notified_generation_id == 4
    assert runtime.is_outage_active is False

def test_idempotent_outage_generation():
    """
    Verifies that repeated broker/Telegram errors during the same outage
    do not increment outage_generation_id more than once.
    """
    runtime = BotRuntimeState()
    sm = StateManager(state_file="data/test_idempotent.json")
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    # Initial failure
    orch._enter_outage("broker", Exception("Fail 1"))
    gen_after_first = runtime.outage_generation_id

    # Repeated failures
    orch._enter_outage("broker", Exception("Fail 2"))
    orch._enter_outage("telegram", Exception("Fail 3"))
    orch._enter_outage("network", Exception("Fail 4"))

    assert runtime.outage_generation_id == gen_after_first, "Generation should not increment during the same outage"
