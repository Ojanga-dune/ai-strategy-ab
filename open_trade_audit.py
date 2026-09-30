import os, requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OANDA_API_KEY')
account_id = os.getenv('OANDA_ACCOUNT_ID')
headers = {"Authorization": f"Bearer {api_key}"}

def main():
    url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/positions"
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        positions = res.json().get('positions', [])
        for p in positions:
            tid = p.get('tradeID')
            # OANDA positions can have a stopLossOrder and takeProfitOrder
            sl_order = p.get('stopLossOrder')
            tp_order = p.get('takeProfitOrder')
            print(f"Trade: {tid} | SL Order: {sl_order} | TP Order: {tp_order}")
    else:
        print(f"Error: {res.status_code}")

if __name__ == '__main__':
    main()
