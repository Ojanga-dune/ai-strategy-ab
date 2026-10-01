import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OANDA_API_KEY")
account_id = os.getenv("OANDA_ACCOUNT_ID")
headers = {"Authorization": f"Bearer {api_key}"}
base = "https://api-fxpractice.oanda.com/v3"

endpoints = [
    f"{base}/accounts/{account_id}/pricing",
    f"{base}/pricing",
    f"{base}/accounts/{account_id}/instruments/XAU_USD/pricing",
]

for url in endpoints:
    try:
        res = requests.get(url, headers=headers, params={"instruments": "XAU_USD"}, timeout=5)
        print(f"URL: {url} | Status: {res.status_code} | Response: {res.text[:100]}")
    except Exception as e:
        print(f"URL: {url} | Exception: {e}")
