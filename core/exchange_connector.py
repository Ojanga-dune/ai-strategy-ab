import os
import logging
import pandas as pd
import requests
import json
from typing import List, Dict, Any, Optional
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from core.precision_utils import round_price
from core.broker_interface import BrokerInterface

logger = logging.getLogger(__name__)

class ExchangeConnector(BrokerInterface):
    """
    OANDA Implementation of the BrokerInterface.
    Handles real-time communication with OANDA API for market data and trade execution.
    """
    def __init__(self, api_key: str, account_id: str, simulation_mode: bool = True):
        self.api_key = api_key
        self.account_id = account_id
        self.simulation_mode = simulation_mode
        self.client = API(access_token=api_key)

        # OANDA API Base URL (Practice/Demo)
        self.base_url = "https://api-fxpractice.oanda.com/v3"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        logger.info(f"ExchangeConnector initialized. Simulation Mode: {simulation_mode}")

    def get_latest_candles(self, instrument: str, granularity: str, count: int = 100) -> pd.DataFrame:
        """
        Fetches the most recent closed candles to feed into the Sieve/AIReviewer.
        """
        logger.info(f"Fetching live candles for {instrument} {granularity}...")
        params = {
            "granularity": granularity,
            "count": count,
        }
        r = instruments.InstrumentsCandles(instrument=instrument.upper(), params=params)
        self.client.request(r)

        candles = r.response.get('candles', [])
        data = []
        for c in candles:
            if c.get('complete'):
                data.append({
                    'time': c['time'],
                    'open': float(c['mid']['o']),
                    'high': float(c['mid']['h']),
                    'low': float(c['mid']['l']),
                    'close': float(c['mid']['c']),
                    'volume': int(c['volume'])
                })

        df = pd.DataFrame(data)
        if df.empty:
            return df

        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)
        return df

    def get_mtf_candles(self, instrument: str, granularities: List[str], count: int = 100) -> Dict[str, pd.DataFrame]:
        """
        Batch fetches candles for multiple timeframes to reduce API calls.
        """
        logger.info(f"Fetching MTF candles for {instrument}: {granularities}...")
        mtf_data = {}
        for gran in granularities:
            df = self.get_latest_candles(instrument, gran, count)
            if not df.empty:
                mtf_data[gran] = df
        return mtf_data

    def place_market_order(self, instrument: str, lots: float, stop_loss: float = None, take_profit: float = None) -> Dict[str, Any]:
        """
        Places a market order.
        NOTE: For OANDA, 'lots' are converted back to 'units' internally.
        """
        # Conversion: 1 Lot = 100,000 units for most forex, but for Gold (XAU_USD) 1 Lot = 100 oz.
        unit_multiplier = 100 if "XAU" in instrument.upper() else 100000
        units = int(lots * unit_multiplier)

        side = "BUY" if units > 0 else "SELL"
        abs_units = abs(units)

        if self.simulation_mode:
            logger.info(f"[SIMULATION] Order Placed: {side} {abs_units} {instrument} @ Market. SL: {stop_loss}, TP: {take_profit}")
            return {"status": "success", "order_id": "sim_123", "simulation": True}

        url = f"{self.base_url}/accounts/{self.account_id}/orders"

        order_payload = {
            "order": {
                "instrument": instrument.upper(),
                "units": str(units),
                "type": "MARKET",
            }
        }

        if stop_loss:
            order_payload["order"]["stopLossOnFill"] = {"price": f"{round_price(stop_loss, instrument):.3f}"}
        if take_profit:
            order_payload["order"]["takeProfitOnFill"] = {"price": f"{round_price(take_profit, instrument):.3f}"}

        try:
            response = requests.post(url, headers=self.headers, json=order_payload, timeout=10)
            if response.status_code in [200, 201]:
                return response.json()
            else:
                logger.error(f"Order failed with status {response.status_code}: {response.text}")
                try:
                    error_data = response.json()
                    msg = error_data.get('message', response.text)
                    if isinstance(msg, list):
                        msg = " | ".join(msg)
                    return {"status": "error", "error_code": response.status_code, "message": msg, "raw": response.text}
                except json.JSONDecodeError:
                    return {"status": "error", "error_code": response.status_code, "message": response.text, "raw": response.text}
        except Exception as e:
            logger.error(f"Order execution request failed: {e}")
            return {"status": "error", "message": str(e), "raw": str(e)}

    def get_account_summary(self) -> Dict[str, Any]:
        """
        Returns current balance and equity for RiskManager calculations.
        """
        url = f"{self.base_url}/accounts/{self.account_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                res = response.json()
                return res.get('account', res)
            else:
                logger.error(f"Failed to fetch account summary: {response.status_code} - {response.text}")
                return {}
        except Exception as e:
            logger.error(f"Account summary request failed: {e}")
            return {}

    def get_open_positions(self, instrument: str = None) -> List[Dict[str, Any]]:
        """
        Returns current open positions for the account.
        """
        url = f"{self.base_url}/accounts/{self.account_id}/positions"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                res = response.json()
                positions = res.get('positions', [])
                if instrument:
                    positions = [p for p in positions if p.get('instrument') == instrument.upper()]
                return positions
            else:
                logger.error(f"Failed to fetch positions: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"Positions request failed: {e}")
            return []

    def get_trade_details(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches details of a specific trade.
        """
        url = f"{self.base_url}/accounts/{self.account_id}/trades/{trade_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json().get('trade')
            else:
                logger.error(f"Failed to fetch trade {trade_id}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Trade details request failed: {e}")
            return None

    def modify_stop_loss(self, trade_id: str, instrument: str, new_sl: float, current_price: float, units: int) -> Dict[str, Any]:
        """
        Modifies the stop loss for an existing trade.
        """
        if self.simulation_mode:
            logger.info(f"[SIMULATION] Stop Loss Updated for {trade_id} to {new_sl}")
            return {"status": "success"}

        url = f"{self.base_url}/accounts/{self.account_id}/orders"
        payload = {
            "order": {
                "tradeID": trade_id,
                "instrument": instrument.upper(),
                "units": str(units),
                "type": "STOP",
                "price": f"{round_price(current_price, instrument):.3f}",
                "stopLossOnFill": {"price": f"{round_price(new_sl, instrument):.3f}"}
            }
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                return response.json()
            else:
                logger.error(f"SL modification failed for {trade_id}: {response.status_code} - {response.text}")
                return {"status": "error", "message": response.text}
        except Exception as e:
            logger.error(f"SL modification request failed: {e}")
            return {"status": "error", "message": str(e)}

    def close_position(self, trade_id: str) -> Dict[str, Any]:
        """
        Closes a specific position.
        In OANDA, closing is essentially placing an opposite order for the same units.
        """
        try:
            # 1. Get current position details from the broker
            positions = self.get_open_positions()
            target_pos = next((p for p in positions if p.get('tradeID') == trade_id), None)

            if not target_pos:
                logger.error(f"Close failed: Trade {trade_id} not found in open positions.")
                return {"status": "error", "message": "Position already closed or not found."}

            # 2. Determine exact units to close
            # OANDA positions have 'long' and 'short' blocks.
            units = 0
            if target_pos.get('long', {}).get('units'):
                units = -int(target_pos['long']['units']) # Close long with a sell
            elif target_pos.get('short', {}).get('units'):
                units = -int(target_pos['short']['units']) # Close short with a buy

            if units == 0:
                return {"status": "error", "message": "Could not determine units to close."}

            instrument = target_pos.get('instrument')
            logger.info(f"Closing position {trade_id}: {instrument} {units} units")

            # 3. Execute the closing order using raw units
            return self._place_units_order(instrument, units)

        except Exception as e:
            logger.error(f"Error closing position {trade_id}: {e}")
            return {"status": "error", "message": str(e)}

    def _place_units_order(self, instrument: str, units: int) -> Dict[str, Any]:
        """Internal helper to place order using raw units, bypassing lot conversion."""
        url = f"{self.base_url}/accounts/{self.account_id}/orders"
        order_payload = {
            "order": {
                "instrument": instrument.upper(),
                "units": str(units),
                "type": "MARKET",
            }
        }
        try:
            response = requests.post(url, headers=self.headers, json=order_payload, timeout=10)
            if response.status_code in [200, 201]:
                return response.json()
            return {"status": "error", "message": response.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def modify_order(self, trade_id: str, stop_loss: float = None, take_profit: float = None) -> Dict[str, Any]:
        """
        Unified modify order method to update SL and/or TP.
        For OANDA v20, we place a new order that targets the existing tradeID to update SL/TP.
        """
        if self.simulation_mode:
            logger.info(f"[SIMULATION] Order {trade_id} modified. SL: {stop_loss}, TP: {take_profit}")
            return {"status": "success"}

        try:
            # 1. Find the position to get current units and instrument
            positions = self.get_open_positions()
            pos = next((p for p in positions if p.get('tradeID') == trade_id), None)
            if not pos:
                return {"status": "error", "message": "Position not found."}

            instrument = pos.get('instrument')
            # Sum total units (long or short)
            units = int(pos.get('long', {}).get('units', 0)) if pos.get('long', {}).get('units') else \
                    int(pos.get('short', {}).get('units', 0))

            # 2. Construct the OANDA update payload
            url = f"{self.base_url}/accounts/{self.account_id}/orders"

            payload = {
                "order": {
                    "tradeID": trade_id,
                    "instrument": instrument.upper(),
                    "units": str(units),
                    "type": "MARKET",
                    "stopLossOnFill": {"price": f"{round_price(stop_loss, instrument):.3f}"} if stop_loss else None,
                    "takeProfitOnFill": {"price": f"{round_price(take_profit, instrument):.3f}"} if take_profit else None
                }
            }
            # Remove None values
            payload["order"] = {k: v for k, v in payload["order"].items() if v is not None}

            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                return response.json()
            else:
                logger.error(f"SL/TP modification failed for {trade_id}: {response.status_code} - {response.text}")
                return {"status": "error", "message": response.text}

        except Exception as e:
            logger.error(f"Error modifying order {trade_id}: {e}")
            return {"status": "error", "message": str(e)}

    def get_trade_transactions(self, trade_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetches all transactions associated with a specific trade, handling pagination.
        Used as a fallback to calculate PnL by summing ORDER_FILL events.
        """
        all_transactions = []
        url = f"{self.base_url}/accounts/{self.account_id}/transactions"
        params = {"tradeID": trade_id}

        try:
            while url:
                response = requests.get(url, headers=self.headers, params=params if '?' not in url else None, timeout=10)
                if response.status_code != 200:
                    logger.error(f"Failed to fetch transactions for trade {trade_id}: {response.status_code}")
                    return None

                data = response.json()
                all_transactions.extend(data.get('transactions', []))

                # Handle Pagination: OANDA returns a 'pages' list
                pages = data.get('pages', [])
                url = pages[0] if pages else None
                params = None # Params are already included in the page URL

            return all_transactions
        except Exception as e:
            logger.error(f"Transaction request failed for trade {trade_id}: {e}")
            return None

    def get_market_price(self, instrument: str) -> Dict[str, float]:
        """
        Fetches current Bid and Ask prices separately.
        """
        url = f"{self.base_url}/pricing"
        params = {"instruments": instrument.upper()}
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                prices = data.get('prices', [])
                if prices:
                    p = prices[0]
                    return {
                        "bid": float(p['b']),
                        "ask": float(p['a']),
                        "mid": float(p['m'])
                    }
            return {}
        except Exception as e:
            logger.error(f"Market price request failed: {e}")
            return {}
