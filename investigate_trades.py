import os
import json
from pathlib import Path
from core.exchange_connector import ExchangeConnector
from dotenv import load_dotenv

load_dotenv()

def main():
    api_key = os.getenv('OANDA_API_KEY')
    account_id = os.getenv('OANDA_ACCOUNT_ID')
    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    
    storage_dir = Path('data/trades')
    cancelled_reasons = {}
    
    for file in storage_dir.glob('*.json'):
        with open(file, 'r') as f:
            data = json.load(f)
            if data.get('reason') == 'Cancelled' or data.get('status') == 'CLOSED' and data.get('pnl') == 0:
                trade_id = file.stem
                try:
                    # Use the trade details to find the real OANDA reason
                    details = exchange.get_trade_details(trade_id)
                    if details:
                        # Look for reason in transaction history if not in details
                        transactions = exchange.get_trade_transactions(trade_id)
                        # Try to find a 'cancel' or 'reject' event
                        reason = 'Unknown'
                        for t in transactions:
                            if t.get('type') == 'ORDER_CANCEL':
                                reason = t.get('reason', 'Cancelled')
                                break
                        cancelled_reasons[reason] = cancelled_reasons.get(reason, 0) + 1
                    else:
                        cancelled_reasons['NOT_FOUND_ON_OANDA'] = cancelled_reasons.get('NOT_FOUND_ON_OANDA', 0) + 1
                except Exception as e:
                    cancelled_reasons[f'ERROR: {str(e)}'] = cancelled_reasons.get(f'ERROR: {str(e)}', 0) + 1
    
    print(json.dumps(cancelled_reasons, indent=2))

if __name__ == '__main__':
    main()
