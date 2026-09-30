import os, json, requests
from pathlib import Path
from dotenv import load_dotenv
from core.exchange_connector import ExchangeConnector

load_dotenv()

def main():
    api_key = os.getenv('OANDA_API_KEY')
    account_id = os.getenv('OANDA_ACCOUNT_ID')
    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    
    storage_dir = Path('data/trades')
    missing_source = []
    for file in storage_dir.glob('*.json'):
        with open(file, 'r') as f:
            data = json.load(f)
            if 'pnl_source' not in data:
                missing_source.append(file.stem)
    
    outcomes = {
        'FILLED': [],
        'CANCELLED/REJECTED': [],
        'NOT_FOUND': []
    }
    
    for order_id in missing_source:
        try:
            # Fetch transactions for this ID
            transactions = exchange.get_trade_transactions(order_id)
            if not transactions:
                # Try getting order details as a fallback to see if it's an orderID
                # We'll just call a generic request here to avoid adding too many methods
                url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/orders/{order_id}"
                headers = {"Authorization": f"Bearer {api_key}"}
                res = requests.get(url, headers=headers)
                if res.status_code == 404:
                    outcomes['NOT_FOUND'].append(order_id)
                elif res.status_code == 200:
                    data = res.json()
                    # If it's an order and not filled, it's cancelled/rejected
                    outcomes['CANCELLED/REJECTED'].append({
                        'id': order_id,
                        'reason': data.get('order', {}).get('state', 'Unknown')
                    })
                else:
                    outcomes['NOT_FOUND'].append(order_id)
            else:
                # Check if any transaction is a fill
                filled = False
                for t in transactions:
                    if t.get('type') == 'ORDER_FILL':
                        trade_id = t.get('tradeOpened', {}).get('tradeID')
                        pnl = t.get('pl', 0)
                        outcomes['FILLED'].append({'order_id': order_id, 'trade_id': trade_id, 'pnl': pnl})
                        filled = True
                        break
                if not filled:
                    outcomes['CANCELLED/REJECTED'].append({
                        'id': order_id,
                        'reason': 'No fill in transactions'
                    })
        except Exception as e:
            outcomes['NOT_FOUND'].append(order_id)
            
    print(json.dumps(outcomes, indent=2))

if __name__ == '__main__':
    main()
