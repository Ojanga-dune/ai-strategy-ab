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
    
    results = {'FILLED': [], 'CANCELLED': [], 'NOT_FOUND': []}
    
    for file in files:
        oid = file.stem
        url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/orders/{oid}"
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json().get('order', {})
            state = data.get('state')
            if state == 'FILLED':
                tid = data.get('tradeOpenedID')
                # Fetch PnL for that trade
                t_url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/trades/{tid}"
                t_res = requests.get(t_url, headers=headers)
                pnl = "Unknown"
                if t_res.status_code == 200:
                    pnl = t_res.json().get('trade', {}).get('realizedPL', '0')
                results['FILLED'].append(f"{oid} (Trade: {tid}, PnL: {pnl})")
            else:
                # Find reason - OANDA order doesn't always have 'reason' field, might be in transactions
                # For now, use state
                results['CANCELLED'].append(f"{oid} (State: {state})")
        else:
            results['NOT_FOUND'].append(oid)
            
    print(f"Total: {len(files)}")
    print(f"FILLED: {len(results['FILLED'])}")
    print(f"CANCELLED: {len(results['CANCELLED'])}")
    print(f"NOT_FOUND: {len(results['NOT_FOUND'])}")
    
    # Count IDs <= 167 vs > 167
    le_167 = 0
    gt_167 = 0
    for file in files:
        try:
            if int(file.stem) <= 167: le_167 += 1
            else: gt_167 += 1
        except ValueError: pass
    
    print(f"IDs <= 167: {le_167}")
    print(f"IDs > 167: {gt_167}")

if __name__ == '__main__':
    main()
