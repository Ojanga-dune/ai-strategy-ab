import os
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from core.exchange_connector import ExchangeConnector
from core.precision_utils import round_price

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("VerifyOneTrade")

def run_verification():
    load_dotenv()
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")

    if not api_key or not account_id:
        logger.error("Missing OANDA_API_KEY or OANDA_ACCOUNT_ID in .env")
        return

    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    
    instrument = "XAU_USD"
    
    # 1. Get current price using the FIXED method in ExchangeConnector
    logger.info(f"Fetching market price for {instrument}...")
    price_data = exchange.get_market_price(instrument)
    
    if not price_data:
        logger.error("Could not fetch market price. Please check API connectivity.")
        return
    
    current_price = price_data['mid']
    # Set a wide SL/TP to ensure it doesn't trigger immediately
    sl = current_price - 10.0
    tp = current_price + 10.0
    
    logger.info(f"Attempting minimum-size order for {instrument}")
    logger.info(f"Entry: {current_price:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")

    # 2. Place Order
    result = exchange.place_market_order(
        instrument=instrument,
        lots=0.01, 
        stop_loss=sl,
        take_profit=tp,
        client_id=f"verify_{int(time.time())}"
    )
    
    if not result or ('orderCreateTransaction' not in result and result.get('status') == 'error'):
        logger.error(f"Order failed: {result}")
        return

    order_id = result.get('orderCreateTransaction', {}).get('id')
    if not order_id:
        logger.error(f"Order placed but no orderID found in response: {result}")
        return

    logger.info(f"Order Placed. OrderID: {order_id}")

    # 3. Extract TradeID from fill
    trade_id = None
    if 'orderFillTransaction' in result:
        trade_id = result['orderFillTransaction'].get('tradeOpened', {}).get('tradeID')
    
    if not trade_id:
        logger.info("TradeID not in response, polling transactions...")
        time.sleep(2)
        trade_id = exchange.get_trade_id_from_order(order_id)

    if not trade_id:
        logger.error(f"Could not resolve TradeID for Order {order_id}")
        return

    logger.info(f"Trade Resolved. TradeID: {trade_id}")

    # 4. Verify SL and TP on the trade
    trade_details = exchange.get_trade_details(trade_id)
    if trade_details:
        sl_actual = trade_details.get('stopLossOnFill', {}).get('price')
        tp_actual = trade_details.get('takeProfitOnFill', {}).get('price')
        logger.info(f"Broker Verified SL: {sl_actual} | TP: {tp_actual}")
    else:
        logger.error("Could not fetch trade details for verification.")

    # 5. Close the trade
    logger.info(f"Closing trade {trade_id}...")
    close_result = exchange.close_position(trade_id)
    
    if close_result.get('status') == 'success' or 'orderCreateTransaction' in close_result:
        logger.info("Trade closed successfully.")
    else:
        logger.error(f"Failed to close trade: {close_result}")

    # 6. Print realized PnL
    time.sleep(2)
    final_details = exchange.get_trade_details(trade_id)
    if final_details:
        realized = final_details.get('realizedPL', 0)
        financing = final_details.get('financing', 0)
        logger.info(f"Final Realized PnL: {realized} | Financing: {financing}")
        logger.info(f"Net PnL: {float(realized) + float(financing):.2f}")
    else:
        logger.error("Could not fetch final trade details for PnL.")

if __name__ == "__main__":
    run_verification()
