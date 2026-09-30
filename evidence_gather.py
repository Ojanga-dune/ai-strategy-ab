import os, json, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def get_data(oid):
    results = {"order": None, "transactions": []}
    # Order details
    url_o = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/orders/{oid}"
    res_o = requests.get(url_o, headers=headers)
    if res_o.status_code == 200:
        results["order"] = res_o.json()
    
    # Transactions
    url_t = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/transactions?instrument=XAU_USD" # Generic check
    # Wait, the user asks for transactions FOR that ID. 
    # OANDA transactions endpoint doesn't filter by orderID directly in the query string.
    # It returns a list. We'll have to filter locally.
    res_t = requests.get(url_t, headers=headers)
    if res_t.status_code == 200:
        all_t = res_t.json().get('transactions', [])
        # Filter transactions related to this order ID (check orderId field)
        related = [t for t in all_t if t.get('orderId') == oid][:4]
        results["transactions"] = related
    return results

for oid in ["4", "101", "171"]:
    print(f"--- ID: {oid} ---")
    print(json.dumps(get_data(oid), indent=2))
