import os
from dotenv import load_dotenv
from core.exchange_connector import ExchangeConnector

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
simulation_mode = True

try:
    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=simulation_mode)
    
    try:
        exchange.get_account_summary()
        print('Account Summary: SUCCESS')
    except Exception as e:
        print(f'Account Summary: FAILED: {e}')
        
    try:
        exchange.get_latest_candles('XAU_USD', 'H1', count=1)
        print('Pricing: SUCCESS')
    except Exception as e:
        print(f'Pricing: FAILED: {e}')
        
    try:
        exchange.get_open_positions()
        print('Open Positions: SUCCESS')
    except Exception as e:
        print(f'Open Positions: FAILED: {e}')
        
except Exception as e:
    print(f'Critical Error: {e}')
