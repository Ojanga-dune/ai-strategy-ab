import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OANDA_API_KEY")
account_id = os.getenv("OANDA_ACCOUNT_ID")

headers = {"Authorization": f"Bearer {api_key}"}
url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions"
response = requests.get(url, headers=headers)
pages = response.json().get('pages', [])

all_txs = []
for page_url in pages:
    p_resp = requests.get(page_url, headers=headers)
    all_txs.extend(p_resp.json().get('transactions', []))

# Filter for the orders mentioned
target_ids = ["158", "159", "162", "164", "167", "171", "189"]
# Note: Order IDs in OANDA are different from our local trade IDs.
# We must look for transactions that occur in the target window or have matching data.
import json
with open("full_tx_history.json", "w") as f:
    json.dump(all_txs, f, indent=4)
