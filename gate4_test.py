import os
import logging
import json
from datetime import datetime
import time
from core.exchange_connector import ExchangeConnector
from core.config import settings
from core.compliance_guard import ComplianceGuard
from core.trade_tracker import TradeTracker

# Gate 4 Safety Variable
CONTROLLED_PRACTICE_TEST = True

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def verify_safety_state():
    logger.info("--- Verifying Safety State ---")
    env = settings.get('oanda_env', 'unknown')
    sim_mode = settings.get('simulation_mode', False)

    logger.info(f"OANDA Environment: {env}")
    logger.info(f"Simulation Mode: {sim_mode}")
    logger.info(f"CONTROLLED_PRACTICE_TEST: {CONTROLLED_PRACTICE_TEST}")

    if env != "practice":
        raise RuntimeError("SAFETY VIOLATION: Environment is not PRACTICE")
    return True

def perform_gate4_test():
    # 1. Setup
    verify_safety_state()

    connector = ExchangeConnector(
        api_key=settings['api_key'],
        account_id=settings['account_id'],
        simulation_mode=False
    )
    tracker = TradeTracker()
    guard = ComplianceGuard()

    instrument = "XAU_USD"

    try:
        # CLEANUP PHASE: If a position exists from previous failed run, close it first
        logger.info("\n--- Cleanup Phase: Checking for stale test positions ---")
        positions = connector.get_open_positions(instrument)
        if positions:
            stale_ids = []
            for p in positions:
                stale_ids.extend(p.get('long', {}).get('tradeIDs', []))
                stale_ids.extend(p.get('short', {}).get('tradeIDs', []))

            if stale_ids:
                logger.info(f"Found {len(stale_ids)} stale trade(s). Closing now...")
                for tid in stale_ids:
                    connector.close_position(tid)
                    logger.info(f"Closed stale trade {tid}")
                time.sleep(2) # Allow broker to update

        # 2. Pre-flight Checks
        logger.info(f"\n--- Pre-flight Checks for {instrument} ---")

        # Final check that we are clean
        positions = connector.get_open_positions(instrument)
        if positions:
            has_active = False
            for p in positions:
                l_units = float(p.get('long', {}).get('units', 0))
                s_units = float(p.get('short', {}).get('units', 0))
                if l_units != 0 or s_units != 0:
                    has_active = True
                    break
            if has_active:
                logger.error("FAILED: Active XAU_USD position still exists. Aborting.")
                return

        summary = connector.get_account_summary()
        if not summary:
            logger.error("FAILED: Account summary unavailable.")
            return

        current_equity = summary['equity']
        guard.update_daily_start(current_equity)
        is_compliant, reason = guard.check_compliance(current_equity, 0.0)
        if not is_compliant:
            logger.error(f"FAILED: Compliance check failed: {reason}")
            return

        prices = connector.get_market_price(instrument)
        if not prices or 'bid' not in prices or 'ask' not in prices:
            logger.error("FAILED: Invalid pricing response.")
            return

        logger.info(f"Pre-flight PASS. Bid: {prices['bid']}, Ask: {prices['ask']}")

        # 3. Execution
        logger.info("\n--- Executing Controlled Practice Order ---")
        lots = 0.01
        client_id = f"gate4_test_{int(datetime.now().timestamp())}"

        if not (settings['oanda_env'] == "practice" and CONTROLLED_PRACTICE_TEST):
            logger.error("HARD SAFETY GUARD TRIGGERED: Execution refused.")
            return

        order_res = connector.place_market_order(
            instrument=instrument,
            lots=lots,
            client_id=client_id
        )

        if order_res.get('status') != 'success':
            logger.error(f"Order failed: {order_res}")
            return

        order_id = order_res.get('orderCreateTransaction', {}).get('id') or order_res.get('id')
        trade_id = order_res.get('orderFillTransaction', {}).get('id')
        logger.info(f"Order Success. OrderID: {order_id}, TradeID: {trade_id}")

        # 4. Tracker Recording
        local_id = f"gate4_{int(datetime.now().timestamp())}"
        trade_dna = {
            "instrument": instrument,
            "side": "BUY" if lots > 0 else "SELL",
            "units": abs(int(lots * 100)),
            "entry_price": prices['ask'],
            "order_id": order_id,
            "trade_id": trade_id,
            "status": "OPEN",
            "client_id": client_id,
            "is_simulated": False
        }
        tracker.record_entry(local_id, trade_dna)
        logger.info(f"Trade DNA recorded for {local_id} in TradeTracker.")

        # 5. Verification
        logger.info("\n--- Verifying Open Trade via API ---")
        pos_list = connector.get_open_positions(instrument)
        all_broker_ids = []
        for p in pos_list:
            all_broker_ids.extend(p.get('long', {}).get('tradeIDs', []))
            all_broker_ids.extend(p.get('short', {}).get('tradeIDs', []))

        if trade_id not in all_broker_ids:
            logger.error(f"FAILED: TradeID {trade_id} not found in broker positions.")
            return

        details = connector.get_trade_details(trade_id)
        if not details or details.get('state') != 'OPEN':
            logger.error(f"FAILED: Trade state is {details.get('state') if details else 'None'}, expected OPEN.")
            return
        logger.info("Trade verified as OPEN and present in aggregated positions.")

        # 6. Controlled Closure
        logger.info("\n--- Executing Controlled Closure ---")
        close_res = connector.close_position(trade_id)
        if close_res.get('status') != 'success':
            logger.error(f"Closure failed: {close_res}")
            return

        time.sleep(2)
        details_closed = connector.get_trade_details(trade_id)
        if not details_closed or details_closed.get('state') != 'CLOSED':
            logger.error(f"FAILED: Trade state is {details_closed.get('state') if details_closed else 'None'}, expected CLOSED.")
            return

        tracker.record_outcome(trade_id, pnl=0.0, status="CLOSED")
        logger.info("Trade verified as CLOSED and updated in tracker.")

        # 7. Reconciliation Check
        logger.info("\n--- Final Reconciliation Check ---")
        final_positions = connector.get_open_positions(instrument)
        final_ids = []
        for p in final_positions:
            final_ids.extend(p.get('long', {}).get('tradeIDs', []))
            final_ids.extend(p.get('short', {}).get('tradeIDs', []))

        if trade_id in final_ids:
            logger.error("FAILED: Phantom position detected.")
            return
        logger.info("Reconciliation verified: No phantom positions.")

    except Exception as e:
        logger.exception(f"Gate 4 Test crashed: {e}")
    finally:
        pass

if __name__ == "__main__":
    perform_gate4_test()
