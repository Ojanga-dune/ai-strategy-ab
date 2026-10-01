import os
import logging
import time
from dotenv import load_dotenv
from core.exchange_connector import ExchangeConnector
from core.precision_utils import round_price

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradeVerifier")

load_dotenv()

def verify_single_trade():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")

    if not api_key or not account_id:
        logger.error("Missing OANDA_API_KEY or OANDA_ACCOUNT_ID in .env")
        return

    # Force simulation_mode=False to test real API connectivity
    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)

    instrument = "XAU_USD"
    lots = 0.01  # Minimum size
    # Use current market price to set a realistic SL/TP
    pricing = exchange.get_market_price(instrument)
    if not pricing:
        logger.error("Could not fetch market price.")
        return

    current_price = pricing['mid']
    sl = current_price - 5.0 if True else current_price + 5.0 # Simple offset
    tp = current_price + 10.0 if True else current_price - 10.0

    try:
        # 1. Place Order
        logger.info(f"Step 1: Placing minimum order for {instrument}...")
        order_result = exchange.place_market_order(
            instrument=instrument,
            lots=lots,
            stop_loss=sl,
            take_profit=tp,
            client_id=f"verify_{int(time.time())}"
        )

        if 'orderCreateTransaction' not in order_result:
            logger.error(f"Order placement failed: {order_result}")
            return

        order_id = order_result['orderCreateTransaction']['id']
        print(f"\n[SUCCESS] Order Placed: Order ID = {order_id}")

        # 2. Resolve Trade ID
        logger.info("Step 2: Resolving Trade ID...")
        trade_id = None

        # Strategy A: Try Transaction Lookup
        trade_id = exchange.get_trade_id_from_order(order_id)

        # Strategy B: Fallback to Open Positions lookup
        if not trade_id:
            logger.info("Transaction lookup failed. Trying Open Positions lookup...")
            positions = exchange.get_open_positions(instrument)
            logger.info(f"Debug: Found {len(positions)} open positions for {instrument}: {positions}")
            for pos in positions:
                long_block = pos.get('long', {})
                short_block = pos.get('short', {})
                long_units = int(float(long_block.get('units', 0)))
                short_units = int(float(short_block.get('units', 0)))
                
                if long_units != 0:
                    tids = long_block.get('tradeIDs', [])
                    if tids:
                        trade_id = tids[0]
                        logger.info(f"Found Trade ID {trade_id} via long position.")
                        break
                elif short_units != 0:
                    tids = short_block.get('tradeIDs', [])
                    if tids:
                        trade_id = tids[0]
                        logger.info(f"Found Trade ID {trade_id} via short position.")
                        break
        
        if not trade_id:
            logger.error("Could not resolve Trade ID via transactions or open positions.")
            return
        print(f"[SUCCESS] Resolved: Trade ID = {trade_id}")
        # 3. Check SL/TP Order IDs
        logger.info("Step 3: Fetching Trade Details for SL/TP IDs...")
        details = exchange.get_trade_details(trade_id)
        if details:
            # OANDA details might contain associated order IDs for SL/TP
            # depending on the API version/response structure
            print(f"[SUCCESS] Trade Details: {details}")
        else:
            logger.warning("Could not fetch trade details.")


        # 4. Close Trade
        logger.info("Step 4: Closing trade...")
        close_result = exchange.close_position(trade_id)
        if close_result.get('status') == 'error':
            logger.error(f"Close failed: {close_result.get('message')}")
            return
        print(f"[SUCCESS] Trade closed successfully.")

        # 5. Print Realized PnL
        logger.info("Step 5: Fetching final realized PnL...")
        final_details = exchange.get_trade_details(trade_id)
        if final_details:
            pnl = final_details.get('realizedPL', 'N/A')
            print(f"[SUCCESS] Final Realized PnL: {pnl}")
        else:
            logger.error("Could not fetch final PnL.")

    except Exception as e:
        logger.exception(f"Verification failed with error: {e}")

if __name__ == "__main__":
    verify_single_trade()
