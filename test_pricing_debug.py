import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OANDA_API_KEY")
account_id = os.getenv("OANDA_ACCOUNT_ID")
headers = {"Authorization": f"Bearer {api_key}"}
url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/pricing"
params = {"instruments": "XAU_USD"}

try:
    res = requests.get(url, headers=headers, params=params, timeout=10)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
except Exception as e:
    print(f"Error: {e}")
