import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def main():
    # Fetch a specific known filled order
    oid = "101"
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/orders/{oid}"
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        order = res.json().get('order', {})
        print(f"Order ID: {order.get('id')}")
        print(f"  SL: {order.get('stopLossOnFill')}")
        print(f"  TP: {order.get('takeProfitOnFill')}")
    else:
        print(f"Error: {res.status_code}")

if __name__ == '__main__':
    main()
