import json
import os

def get_oanda_id(local_id):
    try:
        with open(f"data/trades/{local_id}.json", 'r') as f:
            data = json.load(f)
            return data.get('order_id')
    except:
        return None

targets = ["158", "159", "162", "164", "167", "171", "189"]
oanda_ids = {tid: get_oanda_id(tid) for tid in targets}

with open("full_tx_history.json", 'r') as f:
    txs = json.load(f)

print(f"{'LocalID':<10} | {'OANDA_ID':<15} | {'Reason/Status'}")
print("-" * 40)

for local_id, o_id in oanda_ids.items():
    if not o_id:
        print(f"{local_id:<10} | {'None':<15} | Not found in file")
        continue
    
    # Find transaction with this order ID
    found = False
    for tx in txs:
        # Transactions can be OrderCreate, OrderFill, OrderCancel, etc.
        if tx.get('orderCreateTransaction', {}).get('id') == o_id or \
           tx.get('orderCancelTransaction', {}).get('id') == o_id or \
           tx.get('orderFillTransaction', {}).get('id') == o_id:
            
            if 'orderCancelTransaction' in tx:
                print(f"{local_id:<10} | {o_id:<15} | Cancelled: {tx['orderCancelTransaction'].get('reason')}")
                found = True
            elif 'orderFillTransaction' in tx:
                print(f"{local_id:<10} | {o_id:<15} | FILLED")
                found = True
            elif 'orderCreateTransaction' in tx:
                # If only create exists and no fill/cancel, it might be a pending or lost order
                print(f"{local_id:<10} | {o_id:<15} | Created (No fill/cancel found)")
                found = True
    
    if not found:
        print(f"{local_id:<10} | {o_id:<15} | No transaction found in history")
