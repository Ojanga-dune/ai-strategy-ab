import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def main():
    for tid in ["144", "136"]:
        print(f"--- Trade {tid} ---")
        url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions"
        # OANDA transactions are chronological. We'll filter for this tradeID.
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            txs = res.json().get('transactions', [])
            for t in txs:
                if t.get('tradeID') == tid or (t.get('tradesClosed') and tid in [tc.get('tradeID') for tc in t.get('tradesClosed', [])]):
                    print(f"Tx ID: {t.get('id')} | Type: {t.get('type')} | Reason: {t.get('reason', 'N/A')}")
        else:
            print(f"Error: {res.status_code}")

if __name__ == '__main__':
    main()
