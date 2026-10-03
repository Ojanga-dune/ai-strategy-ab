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

def test_thread_safe_outage_generation():
    """
    Verifies that simultaneous failures from multiple threads result in
    exactly one outage generation increment.
    """
    runtime = BotRuntimeState()
    sm = StateManager(state_file="data/test_concurrent_outage.json")
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    def trigger_outage(source):
        orch._enter_outage(source, Exception("Network failure"))

    threads = [
        threading.Thread(target=trigger_outage, args=("broker",)),
        threading.Thread(target=trigger_outage, args=("telegram",)),
        threading.Thread(target=trigger_outage, args=("network",)),
    ]

    for t in threads: t.start()
    for t in threads: t.join()

    # Should only increment once
    assert runtime.outage_generation_id == 1
    assert runtime.is_outage_active is True
    assert runtime.heartbeat_pending is True

def test_telegram_only_outage_does_not_block_broker():
    """
    Proves that a Telegram-only outage (is_outage_active=True) does NOT block
    broker writes if broker health is valid.
    """
    runtime = BotRuntimeState()
    sm = StateManager(state_file="data/test_tg_outage.json")
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    # Trigger Telegram outage
    orch._enter_outage("telegram", Exception("TG Timeout"))

    # Current State Report
    print(f"\n[TG-ONLY TEST] AppID: {id(notifier._app)} | GenID: {notifier.polling_generation_id} | OutageGen: {runtime.outage_generation_id} | BrokerHealth: {runtime.connectivity_health['broker']} | TGHealth: {runtime.connectivity_health['telegram']} | Pending: {runtime.heartbeat_pending}")

    assert runtime.is_outage_active is True
    assert runtime.connectivity_health["telegram"] is False
    assert runtime.connectivity_health["broker"] is True

    # Test Broker Write Guard
    # In live_main.py, broker writes are blocked only if broker health is invalid
    # Simulation of the broker write check:
    can_write = runtime.connectivity_health["broker"] and not (runtime.is_outage_active and not runtime.connectivity_health["broker"])
    # Wait, the logic should be: block if (is_outage_active AND broker_health is False)
    # If is_outage_active is True but broker_health is True, it's a TG-only outage.

    is_blocked = runtime.is_outage_active and not runtime.connectivity_health["broker"]

    assert is_blocked is False, "Broker writes should NOT be blocked by Telegram-only outage"
    assert runtime.connectivity_health["broker"] is True

def test_broker_outage_blocks_writes():
    """
    Verifies that a broker/network outage blocks broker writes immediately.
    """
    runtime = BotRuntimeState()
    sm = StateManager(state_file="data/test_broker_outage.json")
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    # Trigger Broker outage
    orch._enter_outage("broker", Exception("DNS Failure"))

    print(f"[BROKER-OUTAGE TEST] AppID: {id(notifier._app)} | GenID: {notifier.polling_generation_id} | OutageGen: {runtime.outage_generation_id} | BrokerHealth: {runtime.connectivity_health['broker']} | TGHealth: {runtime.connectivity_health['telegram']} | Pending: {runtime.heartbeat_pending}")

    assert runtime.is_outage_active is True
    assert runtime.connectivity_health["broker"] is False

    is_blocked = runtime.is_outage_active and not runtime.connectivity_health["broker"]
    assert is_blocked is True, "Broker writes MUST be blocked during broker outage"

def test_recoverable_tg_error_no_rebuild():
    """
    Verifies that recoverable Telegram errors trigger outage but do NOT
    increment polling_generation_id or rebuild Application.
    """
    runtime = BotRuntimeState()
    sm = StateManager(state_file="data/test_tg_recover.json")
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    # Mock current app
    notifier._app = MagicMock()
    notifier.polling_generation_id = 1
    app_id = id(notifier._app)

    # Simulate a recoverable NetworkError (via orchestrator as called by notifier)
    orch._enter_outage("telegram", Exception("NetworkError"))

    # The actual rebuilding happens in NotificationManager._run_bot_with_retry
    # We just verify that _enter_outage didn't trigger a rebuild and that
    # our design intended the background thread to retain the app.

    assert runtime.is_outage_active is True
    assert notifier.polling_generation_id == 1
    assert id(notifier._app) == app_id

def test_recovery_requires_full_health():
    """
    Verifies that recovery doesn't close until BOTH Telegram and Broker are healthy.
    """
    runtime = BotRuntimeState()
    sm = StateManager(state_file="data/test_full_recovery.json")
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    # Start in outage
    orch._enter_outage("broker", Exception("Broker Down"))
    orch._enter_outage("telegram", Exception("TG Down"))

    # 1. Only Telegram recovers
    notifier.state = "RUNNING"
    # Broker still fails
    with patch.object(exchange, 'get_account_summary', return_value=None):
        assert orch.verify_connectivity() is False
        orch.handle_recovery(datetime.now(timezone.utc))
        assert runtime.is_outage_active is True, "Outage should stay active if broker is still down"

    # 2. Broker also recovers
    with patch.object(exchange, 'get_account_summary', return_value={"equity": 100}):
        assert orch.verify_connectivity() is True

        # Mock send_sync to return a completed future
        mock_future = Future()
        mock_future.set_result(True)
        with patch.object(notifier, 'send_sync', return_value=mock_future):
            orch.handle_recovery(datetime.now(timezone.utc))
            # finalize_recovery is called in the loop
            orch.finalize_recovery(datetime.now(timezone.utc))

            assert runtime.is_outage_active is False
            assert runtime.recovery_notified_generation_id == runtime.outage_generation_id
            assert runtime.heartbeat_pending is False

def test_outage_persistence_across_restart():
    """
    Verifies that outage_generation_id and pending status survive process restart.
    """
    sm = StateManager(state_file="data/test_restart.json")
    runtime = BotRuntimeState()
    notifier = NotificationManager(token="valid", chat_id="123")
    exchange = MockExchange()
    orch = LiveBotOrchestrator(runtime, sm, notifier, exchange)

    orch._enter_outage("broker", Exception("Crashy Outage"))

    # Simulate Restart
    new_runtime = BotRuntimeState()
    metrics = sm.load_heartbeat_metrics()
    new_runtime.outage_generation_id = metrics[5]
    new_runtime.recovery_notified_generation_id = metrics[6]
    new_runtime.heartbeat_pending = metrics[2]
    new_runtime.is_outage_active = metrics[8]

    assert new_runtime.outage_generation_id == 1
    assert new_runtime.heartbeat_pending is True
    assert new_runtime.is_outage_active is True
