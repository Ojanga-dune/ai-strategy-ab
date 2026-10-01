import sys
import os
import logging
from unittest.mock import MagicMock

# Add current directory to path to allow imports from live_main
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging as py_logging
py_logging.basicConfig(level=py_logging.INFO)
logger = py_logging.getLogger("Test")

try:
    from live_main import manage_active_trades
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

def run_test(name, mock_broker_resp, mock_tracker_resp):
    print(f"\n--- Test: {name} ---")
    mock_exchange = MagicMock()
    mock_tracker = MagicMock()
    mock_notifier = MagicMock()
    
    # Mock ExchangeConnector.get_open_positions
    mock_exchange.get_open_positions.return_value = mock_broker_resp
    # Mock TradeTracker.get_open_trades
    mock_tracker.get_open_trades.return_value = mock_tracker_resp
    
    # Execute
    manage_active_trades(mock_exchange, mock_tracker, mock_notifier, "XAU_USD")

if __name__ == "__main__":
    # a) Position exists (Synced)
    run_test("Position Exists (Synced)", 
             [{"tradeID": "T1", "instrument": "XAU_USD"}], 
             [{"local_id": "L1", "trade_id": "T1", "instrument": "XAU_USD"}])
    
    # b) Position legitimately closed (Missing from broker)
    run_test("Position Closed (Broker Empty)", 
             [], 
             [{"local_id": "L1", "trade_id": "T1", "instrument": "XAU_USD"}])
    
    # c) Broker returns empty list successfully
    run_test("Broker Empty List", 
             [], 
             [])
    
    # d) Broker request fails/times out
    def fail_call(*args, **kwargs):
        raise Exception("API Timeout")
    
    print("\n--- Test: Broker Request Fails ---")
    mock_exchange = MagicMock()
    mock_exchange.get_open_positions.side_effect = fail_call
    mock_tracker = MagicMock()
    mock_tracker.get_open_trades.return_value = [{"local_id": "L1"}]
    mock_notifier = MagicMock()
    manage_active_trades(mock_exchange, mock_tracker, mock_notifier, "XAU_USD")
    
    # e) Tracker contains stale trade
    run_test("Tracker Stale Trade", 
             [{"tradeID": "T2", "instrument": "XAU_USD"}], 
             [{"local_id": "L1", "trade_id": "T1", "instrument": "XAU_USD"}])
