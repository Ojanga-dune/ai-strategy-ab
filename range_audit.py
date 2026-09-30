import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}
# Using the idrange endpoint to see everything between 100 and 167
url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions/idrange?from=100&to=167"
res = requests.get(url, headers=headers)
if res.status_code == 200:
    txs = res.json().get('transactions', [])
    for t in txs:
        print(f"ID: {t.get('id')} | Type: {t.get('type')} | Data: {t}")
else:
    print(f"Error: {res.status_code} - {res.text}")
