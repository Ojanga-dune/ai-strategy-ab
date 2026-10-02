import os
import logging
import pandas as pd
import requests
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from core.precision_utils import round_price
from core.broker_interface import BrokerInterface

logger = logging.getLogger(__name__)

class ExchangeConnector(BrokerInterface):
    """
    OANDA Implementation of the BrokerInterface.
    Handles real-time communication with OANDA API for market data and trade execution.
    Implements strict Fail-Closed architecture for Authentication failures.
    """
    def __init__(self, api_key: str, account_id: str, simulation_mode: bool = True):
        self.api_key = api_key
        self.account_id = account_id
        self.simulation_mode = simulation_mode

        # Connection state
        self.connection_status = "UNKNOWN" # CONNECTED, DEGRADED, DISCONNECTED, AUTH_FAILED, RECOVERING
        self._last_success_time = None
        self._consecutive_failures = 0

        # Auth Failure Tracking
        self._auth_failure_logged = False
        self.auth_failure_reason = None # "401 Unauthorized" or "403 Forbidden"
        self.auth_failed_since = None
        self.last_auth_probe_time = None
        self.next_auth_probe_time = None
        self.consecutive_auth_failures = 0
        self.auth_probe_interval = 3600 # Default 1 hour

        self.client = API(access_token=api_key)

        # OANDA API Base URL (Practice/Demo)
        self.base_url = "https://api-fxpractice.oanda.com/v3"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        logger.info(f"ExchangeConnector initialized. Simulation Mode: {simulation_mode}")

    # --- Authorization Guard ---

    def _check_auth_guard(self, operation: str) -> Tuple[bool, Optional[str]]:
        """
        Centralized guard for all broker-facing write operations.
        Returns (is_allowed, error_message).
        """
        if self.connection_status == "AUTH_FAILED":
            reason = self.auth_failure_reason or "Authentication Failed"
            msg = f"Operation {operation} blocked: {reason}. Broker connectivity lost."
            logger.warning(msg)
            return False, msg

        if self.connection_status == "RECOVERING":
            msg = f"Operation {operation} blocked: Broker is currently RECOVERING. Awaiting reconciliation."
            logger.warning(msg)
            return False, msg

        return True, None

    # --- Auth Recovery Logic ---

    def _run_auth_probe(self) -> bool:
        """
        Performs a lightweight, read-only authentication probe.
        Bypasses the AUTH_FAILED short-circuit.
        """
        logger.info("Performing OANDA Auth Recovery Probe...")
        url = f"{self.base_url}/accounts/{self.account_id}"
        try:
            # We use requests directly to bypass the internal state guards
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                logger.info("Auth Recovery Probe: SUCCESS. Broker identity verified.")
                return True
            elif response.status_code in [401, 403]:
                logger.warning(f"Auth Recovery Probe: FAILED (Status {response.status_code}).")
                return False
            else:
                logger.warning(f"Auth Recovery Probe: UNEXPECTED STATUS {response.status_code}.")
                return False
        except Exception as e:
            logger.warning(f"Auth Recovery Probe: EXCEPTION {e}.")
            return False

    def handle_auth_recovery(self, state_manager: Any = None):
        """
        Manages the recovery transition from AUTH_FAILED -> CONNECTED.
        Should be called periodically in the main loop.
        """
        if self.connection_status != "AUTH_FAILED":
            return

        now = datetime.now(timezone.utc)
        if self.next_auth_probe_time and now < self.next_auth_probe_time:
            return

        if self._run_auth_probe():
            # Transition to RECOVERING
            self.connection_status = "RECOVERING"
            logger.info("Broker status changed to RECOVERING. Starting mandatory reconciliation...")

            # Mandatory Verification Sequence
            # 1. Reconciliation (passed via state_manager)
            if state_manager:
                broker_positions = self.get_open_positions(bypass_guard=True)
                if broker_positions is None:
                    logger.error("Recovery Failed: Could not fetch positions for reconciliation.")
                    self.connection_status = "AUTH_FAILED"
                    return

                synced, reason = state_manager.reconcile_with_broker(broker_positions)
                if not synced:
                    logger.error(f"Recovery Failed: Reconciliation mismatch ({reason}). Staying fail-closed.")
                    self.connection_status = "AUTH_FAILED"
                    return

            # 2. Verify basic account access
            if self.get_account_summary(bypass_guard=True) is None:
                logger.error("Recovery Failed: Account summary verification failed.")
                self.connection_status = "AUTH_FAILED"
                return

            # 3. Final transition
            downtime = now - self.auth_failed_since if self.auth_failed_since else None
            duration_str = f"{downtime.total_seconds()/3600:.2f} hours" if downtime else "unknown"

            logger.info(f"AUTH RESTORED. Downtime: {duration_str}. Reconciliation: SUCCESS.")
            self.connection_status = "CONNECTED"
            self._auth_failure_logged = False
            self.consecutive_auth_failures = 0
            self.auth_failure_reason = None
            self.auth_failed_since = None
        else:
            # Still failed
            self.consecutive_auth_failures += 1
            self.last_auth_probe_time = now
            self.next_auth_probe_time = now + timedelta(seconds=self.auth_probe_interval)

    # --- Market Data (Read Operations) ---

    def get_latest_candles(self, instrument: str, granularity: str, count: int = 100) -> pd.DataFrame:
        """
        Fetches candles. If AUTH_FAILED, returns an empty DataFrame but logs specifically.
        """
        if self.connection_status == "AUTH_FAILED":
            # Explicitly distinguish auth failure from empty data
            logger.warning(f"Candle fetch for {instrument} blocked: {self.auth_failure_reason}. (Auth Failure)")
            return pd.DataFrame()

        logger.info(f"Fetching live candles for {instrument} {granularity}...")
        params = {"granularity": granularity, "count": count}
        try:
            r = instruments.InstrumentsCandles(instrument=instrument.upper(), params=params)
            self.client.request(r)
            self._update_connection_status(True)
        except Exception as e:
            status_code = getattr(e, 'status', None)
            logger.error(f"Error fetching candles: {e}")
            self._update_connection_status(False, status_code=status_code)
            return pd.DataFrame()

        candles = r.response.get('candles', [])
        data = []
        for c in candles:
            if c.get('complete'):
                data.append({
                    'time': c['time'], 'open': float(c['mid']['o']),
                    'high': float(c['mid']['h']), 'low': float(c['mid']['l']),
                    'close': float(c['mid']['c']), 'volume': int(c['volume'])
                })
        df = pd.DataFrame(data)
        if df.empty: return df
        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)
        return df

    def get_mtf_candles(self, instrument: str, granularities: List[str], count: int = 100) -> Dict[str, pd.DataFrame]:
        logger.info(f"Fetching MTF candles for {instrument}: {granularities}...")
        mtf_data = {}
        for gran in granularities:
            df = self.get_latest_candles(instrument, gran, count)
            if not df.empty: mtf_data[gran] = df
        return mtf_data

    # --- Write Operations (Guarded) ---

    def place_market_order(self, instrument: str, lots: float, stop_loss: float = None, take_profit: float = None, client_id: str = None) -> Dict[str, Any]:
        allowed, msg = self._check_auth_guard("place_market_order")
        if not allowed: return {"status": "error", "message": msg}

        unit_multiplier = 100 if "XAU" in instrument.upper() else 100000
        units = int(lots * unit_multiplier)
        side = "BUY" if units > 0 else "SELL"
        abs_units = abs(units)

        if self.simulation_mode:
            logger.info(f"[SIMULATION] Order Placed: {side} {abs_units} {instrument} @ Market. SL: {stop_loss}, TP: {take_profit}, ClientID: {client_id}")
            return {"status": "success", "order_id": "sim_123", "simulation": True}

        url = f"{self.base_url}/accounts/{self.account_id}/orders"
        order_payload = {"order": {"instrument": instrument.upper(), "units": str(units), "type": "MARKET"}}
        if client_id: order_payload["order"]["clientExtensions"] = {"id": client_id}
        if stop_loss: order_payload["order"]["stopLossOnFill"] = {"price": f"{round_price(stop_loss, instrument):.3f}"}
        if take_profit: order_payload["order"]["takeProfitOnFill"] = {"price": f"{round_price(take_profit, instrument):.3f}"}

        try:
            response = requests.post(url, headers=self.headers, json=order_payload, timeout=10)
            if response.status_code in [200, 201]:
                res = response.json()
                if 'orderCreateTransaction' in res: return {"status": "success", **res}
                return res
            else:
                self._update_connection_status(False, status_code=response.status_code)
                logger.error(f"Order failed with status {response.status_code}: {response.text}")
                try:
                    error_data = response.json()
                    msg = error_data.get('message', response.text)
                    if isinstance(msg, list): msg = " | ".join(msg)
                    return {"status": "error", "error_code": response.status_code, "message": msg, "raw": response.text}
                except json.JSONDecodeError:
                    return {"status": "error", "error_code": response.status_code, "message": response.text, "raw": response.text}
        except Exception as e:
            logger.error(f"Order execution request failed: {e}")
            self._update_connection_status(False)
            return {"status": "error", "message": str(e), "raw": str(e)}

    def modify_order(self, trade_id: str, stop_loss: float = None, take_profit: float = None) -> Dict[str, Any]:
        allowed, msg = self._check_auth_guard("modify_order")
        if not allowed: return {"status": "error", "message": msg}

        if self.simulation_mode:
            logger.info(f"[SIMULATION] Order {trade_id} modified. SL: {stop_loss}, TP: {take_profit}")
            return {"status": "success"}

        try:
            positions = self.get_open_positions()
            pos = next((p for p in positions if trade_id in p.get('long', {}).get('tradeIDs', []) or trade_id in p.get('short', {}).get('tradeIDs', [])), None)
            if not pos: return {"status": "error", "message": "Position not found."}

            instrument = pos.get('instrument')
            units = int(float(pos.get('long', {}).get('units', 0))) if pos.get('long', {}).get('units') else \
                    int(float(pos.get('short', {}).get('units', 0)))

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
            payload["order"] = {k: v for k, v in payload["order"].items() if v is not None}
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                res = response.json()
                if 'orderCreateTransaction' in res: return {"status": "success", **res}
                return res
            else:
                logger.error(f"SL/TP modification failed for {trade_id}: {response.status_code} - {response.text}")
                return {"status": "error", "message": response.text}
        except Exception as e:
            logger.error(f"Error modifying order {trade_id}: {e}")
            return {"status": "error", "message": str(e)}

    def close_position(self, trade_id: str) -> Dict[str, Any]:
        allowed, msg = self._check_auth_guard("close_position")
        if not allowed: return {"status": "error", "message": msg}

        try:
            positions = self.get_open_positions()
            target_pos = next((p for p in positions if trade_id in p.get('long', {}).get('tradeIDs', []) or trade_id in p.get('short', {}).get('tradeIDs', [])), None)
            if not target_pos:
                logger.error(f"Close failed: Trade {trade_id} not found in open positions.")
                return {"status": "error", "message": "Position already closed or not found."}

            units = 0
            if target_pos.get('long', {}).get('units'):
                units = -int(float(target_pos['long']['units']))
            elif target_pos.get('short', {}).get('units'):
                units = -int(float(target_pos['short']['units']))

            if units == 0: return {"status": "error", "message": "Could not determine units to close."}
            instrument = target_pos.get('instrument')
            logger.info(f"Closing position {trade_id}: {instrument} {units} units")
            return self._place_units_order(instrument, units)
        except Exception as e:
            logger.error(f"Error closing position {trade_id}: {e}")
            return {"status": "error", "message": str(e)}

    def _place_units_order(self, instrument: str, units: int) -> Dict[str, Any]:
        """Internal helper to place orders using raw units. Also guarded."""
        allowed, msg = self._check_auth_guard("raw_units_order")
        if not allowed: return {"status": "error", "message": msg}

        if self.simulation_mode:
            return {"status": "success", "simulation": True}

        url = f"{self.base_url}/accounts/{self.account_id}/orders"
        payload = {"order": {"instrument": instrument.upper(), "units": str(units), "type": "MARKET"}}
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if response.status_code in [200, 201]: return {"status": "success", **response.json()}
            return {"status": "error", "message": response.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # --- Account Summary & Positions (Bypassable for probes) ---

    def get_account_summary(self, bypass_guard: bool = False) -> Optional[Dict[str, Any]]:
        if not bypass_guard and self.connection_status == "AUTH_FAILED":
            logger.warning("Account summary fetch blocked: AUTH_FAILED.")
            return None

        url = f"{self.base_url}/accounts/{self.account_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                self._update_connection_status(True)
                res = response.json()
                account = res.get('account', res)
                nav = account.get('NAV')
                balance = account.get('balance')
                try:
                    equity = float(nav) if nav is not None else None
                    balance = float(balance) if balance is not None else None
                except (ValueError, TypeError):
                    equity, balance = None, None

                if equity is None or balance is None or equity <= 0:
                    logger.error(f"Account data invalid or missing (NAV: {nav}, Balance: {balance})")
                    return None

                return {"equity": equity, "balance": balance, "account_id": account.get('id'), "currency": account.get('currency'), "raw": account}
            else:
                self._update_connection_status(False, status_code=response.status_code)
                logger.error(f"Failed to fetch account summary: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            self._update_connection_status(False)
            logger.error(f"Account summary request failed: {e}")
            return None

    def get_open_positions(self, instrument: str = None, bypass_guard: bool = False) -> List[Dict[str, Any]]:
        if not bypass_guard and self.connection_status == "AUTH_FAILED":
            logger.warning("Positions fetch blocked: AUTH_FAILED.")
            return None

        url = f"{self.base_url}/accounts/{self.account_id}/positions"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                self._update_connection_status(True)
                res = response.json()
                positions = res.get('positions', [])
                if instrument:
                    positions = [p for p in positions if p.get('instrument') == instrument.upper()]
                return positions
            else:
                self._update_connection_status(False, status_code=response.status_code)
                logger.error(f"Failed to fetch positions: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            self._update_connection_status(False)
            logger.error(f"Positions request failed: {e}")
            return None

    def get_trade_details(self, trade_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/accounts/{self.account_id}/trades/{trade_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200: return response.json().get('trade')
            return None
        except Exception as e:
            logger.error(f"Trade details request failed: {e}")
            return None

    # --- Remaining Helpers ---

    def get_account_transactions(self, from_time: str, to_time: str) -> List[Dict[str, Any]]:
        all_transactions = []
        url = f"{self.base_url}/accounts/{self.account_id}/transactions"
        params = {"from": from_time, "to": to_time, "paginate": "true"}
        try:
            while url:
                response = requests.get(url, headers=self.headers, params=params if '?' not in url else None, timeout=10)
                if response.status_code != 200: return all_transactions
                data = response.json()
                all_transactions.extend(data.get('transactions', []))
                pages = data.get('pages', [])
                url = pages[0] if pages else None
                params = None
            return all_transactions
        except Exception as e:
            logger.error(f"Transaction fetch request failed: {e}")
            return all_transactions

    def check_order_exists(self, client_id: str) -> bool:
        if self.simulation_mode: return False
        url = f"{self.base_url}/accounts/{self.account_id}/orders"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                orders = response.json().get('orders', [])
                for order in orders:
                    if order.get('clientExtensions', {}).get('id') == client_id: return True
        except Exception as e:
            logger.error(f"Error checking if order {client_id} exists: {e}")
        return False

    def get_trade_id_from_order(self, order_id: str) -> Optional[str]:
        try:
            from datetime import timedelta
            from_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            to_time = datetime.now(timezone.utc).isoformat()
            transactions = self.get_account_transactions(from_time, to_time)
            search_oid = str(order_id)
            for tx in transactions:
                if str(tx.get('orderID', '')) == search_oid and tx.get('tradeID'):
                    return tx.get('tradeID')
            return None
        except Exception as e:
            logger.error(f'Error resolving trade ID from order {order_id}: {e}')
            return None

    def get_market_price(self, instrument: str) -> Dict[str, float]:
        url = f"{self.base_url}/accounts/{self.account_id}/pricing"
        params = {"instruments": instrument.upper()}
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                prices = data.get('prices', [])
                if prices:
                    p = prices[0]
                    bids, asks = p.get('bids', []), p.get('asks', [])
                    if not bids or not asks: return {}
                    return {"bid": float(bids[0]['price']), "ask": float(asks[0]['price']), "mid": (float(bids[0]['price']) + float(asks[0]['price'])) / 2}
            return {}
        except Exception as e:
            logger.error(f"Market price request failed: {e}")
            return {}

    def _update_connection_status(self, success: bool, status_code: Optional[int] = None):
        if success:
            self._last_success_time = datetime.now(timezone.utc)
            self._consecutive_failures = 0
            self.connection_status = "CONNECTED"
            self._auth_failure_logged = False
            self.auth_failure_reason = None
            self.auth_failed_since = None
        else:
            self._consecutive_failures += 1
            now = datetime.now(timezone.utc)
            if status_code in [401, 403]:
                self.connection_status = "AUTH_FAILED"
                self.auth_failure_reason = "401 Unauthorized" if status_code == 401 else "403 Forbidden"
                self.auth_failed_since = now
                if not self._auth_failure_logged:
                    logger.critical(f"OANDA Authentication Failed ({self.auth_failure_reason}) at {now}. Broker connectivity lost. Check API Key.")
                    self._auth_failure_logged = True
                return
            if self._consecutive_failures >= 3:
                self.connection_status = "DISCONNECTED"
            elif self._last_success_time and (now - self._last_success_time).total_seconds() > 300:
                self.connection_status = "DISCONNECTED"
            else:
                self.connection_status = "DEGRADED"
