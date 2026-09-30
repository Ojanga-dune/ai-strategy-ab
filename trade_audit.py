import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}
url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/trades?state=ALL&count=500"
res = requests.get(url, headers=headers)
if res.status_code == 200:
    trades = res.json().get('trades', [])
    print(f"Count: {len(trades)}")
    for t in trades:
        print(t.get('tradeID'))
else:
    print(f"Error: {res.status_code}")
