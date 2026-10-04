import pytest
from unittest.mock import MagicMock, patch
from live_main import cmd_status
from core.runtime_state import BotRuntimeState
from core.notifications import NotificationManager
from core.exchange_connector import ExchangeConnector
from core.compliance_guard import ComplianceGuard
from core.trade_tracker import TradeTracker
from core.circuit_breaker import CircuitBreaker

class TestStatusDisplay:
    @pytest.fixture
    def setup_status(self):
        runtime = BotRuntimeState()
        exchange = MagicMock(spec=ExchangeConnector)
        compliance = MagicMock(spec=ComplianceGuard)
        tracker = MagicMock(spec=TradeTracker)
        breaker = MagicMock(spec=CircuitBreaker)
        notifier = MagicMock(spec=NotificationManager)
        
        # Defaults
        runtime.cycle_count = 10
        runtime.last_cycle_timestamp = None
        exchange.connection_status = "CONNECTED"
        notifier.state = "RUNNING"
        breaker.is_tripped.return_value = False
        
        return {
            "runtime": runtime,
            "exchange": exchange,
            "compliance": compliance,
            "tracker": tracker,
            "breaker": breaker,
            "notifier": notifier
        }

    def test_equity_available(self, setup_status):
        s = setup_status
        s['runtime'].is_account_available = True
        s['exchange'].get_account_summary.return_value = {"equity": 1234.56, "balance": 1200.0}
        
        report = cmd_status("status", None, s['exchange'], s['runtime'], s['compliance'], s['tracker'], s['breaker'], s['notifier'])
        assert "Equity: $1234.56" in report
        assert "(Stale)" not in report

    def test_equity_unavailable_stale(self, setup_status):
        s = setup_status
        s['runtime'].is_account_available = False
        s['exchange'].get_account_summary.return_value = {"equity": 1234.56, "balance": 1200.0}
        
        report = cmd_status("status", None, s['exchange'], s['runtime'], s['compliance'], s['tracker'], s['breaker'], s['notifier'])
        assert "Equity: $1234.56 (Stale)" in report

    def test_equity_none(self, setup_status):
        s = setup_status
        s['runtime'].is_account_available = False
        s['exchange'].get_account_summary.return_value = None
        
        report = cmd_status("status", None, s['exchange'], s['runtime'], s['compliance'], s['tracker'], s['breaker'], s['notifier'])
        assert "Equity: N/A" in report

    def test_equity_available_none(self, setup_status):
        s = setup_status
        s['runtime'].is_account_available = True
        s['exchange'].get_account_summary.return_value = None
        
        report = cmd_status("status", None, s['exchange'], s['runtime'], s['compliance'], s['tracker'], s['breaker'], s['notifier'])
        assert "Equity: N/A" in report
