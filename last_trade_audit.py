import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def main():
    # Get last 50 transactions to find the last close
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions"
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        txs = res.json().get('transactions', [])
        # Find the last trade that closed
        for t in reversed(txs):
            if t.get('type') == 'ORDER_FILL' and t.get('tradesClosed'):
                print(f"Last Close Found: Transaction {t.get('id')}")
                print(f"Type: {t.get('type')}")
                print(f"Trades Closed: {t.get('tradesClosed')}")
                print(f"Reason: {t.get('reason')}")
                break
    else:
        print(f"Error: {res.status_code}")

if __name__ == '__main__':
    main()
