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
    
    not_found = []
    cancelled = []
    
    for file in files:
        oid = file.stem
        url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/orders/{oid}"
        res = requests.get(url, headers=headers)
        if res.status_code == 404:
            not_found.append(oid)
        elif res.status_code == 200:
            state = res.json().get('order', {}).get('state')
            if state != 'FILLED':
                reason = "Unknown"
                # Try to get reason from transactions
                tx_url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions?orderId={oid}"
                tx_res = requests.get(tx_url, headers=headers)
                if tx_res.status_code == 200:
                    txs = tx_res.json().get('transactions', [])
                    for t in txs:
                        if t.get('type') in ['ORDER_CANCEL', 'ORDER_REJECT']:
                            reason = t.get('reason', 'Unknown')
                            break
                cancelled.append(f"{oid} | {state} | {reason}")
    
    print(f"404s ({len(not_found)}):")
    print(", ".join(not_found))
    print(f"\nCancelled/Rejected ({len(cancelled)}):")
    print("\n".join(cancelled))
    
    # IDs <= 167 among 404s
    le_167 = [id for id in not_found if id.isdigit() and int(id) <= 167]
    print(f"\n404s <= 167: {len(le_167)}")
    print(", ".join(le_167))

if __name__ == '__main__':
    main()
