import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def fetch(oid):
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/orders/{oid}"
    res = requests.get(url, headers=headers)
    return res.status_code, res.json() if res.status_code == 200 else None

for oid in ["4", "101", "171"]:
    code, data = fetch(oid)
    print(f"ID {oid} -> Status: {code}, Data: {data}")
