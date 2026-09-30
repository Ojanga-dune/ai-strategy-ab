import json
import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}
url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}"
res = requests.get(url, headers=headers)
if res.status_code == 200:
    print(json.dumps(res.json().get('account', {}), indent=2))
else:
    print(f"Error: {res.status_code}")
