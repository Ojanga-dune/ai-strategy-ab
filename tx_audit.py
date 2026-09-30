import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def main():
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions"
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        txs = res.json().get('transactions', [])
        # Transactions IDs are strings, we'll find those in range 160-167
        # Note: IDs are not necessarily sequential integers, but we'll check
        for t in txs:
            tid = t.get('id', '')
            if tid and tid.isdigit() and 160 <= int(tid) <= 167:
                print(f"ID: {tid} | Type: {t.get('type')} | Data: {t}")
    else:
        print(f"Error: {res.status_code}")

if __name__ == '__main__':
    main()
