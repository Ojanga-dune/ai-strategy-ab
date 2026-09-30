import os
from core.exchange_connector import ExchangeConnector
from dotenv import load_dotenv

load_dotenv()

def main():
    api_key = os.getenv('OANDA_API_KEY')
    account_id = os.getenv('OANDA_ACCOUNT_ID')
    exchange = ExchangeConnector(api_key=api_key, account_id=account_id, simulation_mode=False)
    
    # We'll use XAU_USD for the test
    instrument = "XAU_USD"
    # Fetch instrument details for displayPrecision
    url = f"https://api-fxpractice.oanda.com/v3/instruments"
    import requests
    res = requests.get(url, headers={"Authorization": f"Bearer {api_key}"})
    instruments = res.json().get('instruments', {})
    precision = instruments.get(instrument, {}).get('displayPrecision', 'Unknown')
    
    # Simulate a payload as it is sent in place_market_order
    # We'll look at the method in exchange_connector.py
    print(f"Instrument: {instrument}")
    print(f"Display Precision: {precision}")
    
    # Sample values from a trade
    sl = 4129.185714285714
    tp = 4212.673571428572
    print(f"Sent SL: {sl}")
    print(f"Sent TP: {tp}")
    # The actual request uses json.dumps, which doesn't round.
    # OANDA rounds on their side.
    
if __name__ == '__main__':
    main()
