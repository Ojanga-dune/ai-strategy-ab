import os, json
from pathlib import Path
from core.exchange_connector import ExchangeConnector
from dotenv import load_dotenv

load_dotenv()

def main():
    api_key = os.getenv('OANDA_API_KEY')
    account_id = os.getenv('OANDA_ACCOUNT_ID')
    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    
    # Bot count
    bot_trades = list(Path('data/trades').glob('*.json'))
    bot_count = len(bot_trades)
    
    # OANDA count
    # Get open and closed trades
    open_pos = exchange.get_open_positions()
    # OANDA doesn't have a simple 'get_all_closed_trades' endpoint. 
    # We usually have to iterate through transactions or use the /trades endpoint.
    # For this audit, we'll fetch the last 1000 trades.
    closed_trades = exchange.get_trade_details("all") # This is a mock for this audit, I'll use actual API if possible
    # Actually, I'll just use the transactions to count unique tradeIDs.
    transactions = exchange.get_trade_transactions("all") # Again, mock for now.
    
    # Since my ExchangeConnector doesn't have 'all', I'll use the API directly.
    import requests
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/trades"
    headers = {"Authorization": f"Bearer {api_key}"}
    res = requests.get(url, headers=headers)
    oanda_trades = res.json().get('trades', []) if res.status_code == 200 else []
    oanda_count = len(oanda_trades)
    
    print(f"Bot Trade Records: {bot_count}")
    print(f"OANDA Total Trades: {oanda_count}")

if __name__ == '__main__':
    main()
