import os, json, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def main():
    storage_dir = Path('data/trades')
    files = list(storage_dir.glob('*.json'))
    
    all_transactions = []
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions"
    while url:
        res = requests.get(url, headers=headers)
        if res.status_code != 200: break
        data = res.json()
        all_transactions.extend(data.get('transactions', []))
        pages = data.get('pages', [])
        url = pages[0] if pages else None
    
    order_map = {}
    for t in all_transactions:
        oid = t.get('orderId')
        if oid:
            if oid not in order_map: order_map[oid] = []
            order_map[oid].append(t)
    
    results = {'FILLED': 0, 'CANCELLED_REJECTED': 0, 'NOT_ON_OANDA': 0}
    table = []
    
    for file in files:
        fid = file.stem
        if fid in order_map:
            txs = order_map[fid]
            is_filled = any(tx.get('type') == 'ORDER_FILL' for tx in txs)
            if is_filled:
                results['FILLED'] += 1
                table.append(f'{fid} | FILLED')
            else:
                reason = 'Unknown'
                for tx in txs:
                    if tx.get('type') in ['ORDER_CANCEL', 'ORDER_REJECT']:
                        reason = tx.get('reason', 'Unknown')
                        break
                results['CANCELLED_REJECTED'] += 1
                table.append(f'{fid} | CANCELLED_REJECTED | {reason}')
        else:
            results['NOT_ON_OANDA'] += 1
            table.append(f'{fid} | NOT_ON_OANDA')
            
    print(f'Total Files: {len(files)}')
    print(f'FILLED: {results["FILLED"]}')
    print(f'CANCELLED_REJECTED: {results["CANCELLED_REJECTED"]}')
    print(f'NOT_ON_OANDA: {results["NOT_ON_OANDA"]}')
    print('\n--- Detail Table ---')
    print('\n'.join(table))

if __name__ == '__main__':
    main()
