# Implementation Plan: Fix 'TBD' PnL Bug and PnL Attribution

## Objective
Eliminate "TBD" PnL markers in trade outcomes by implementing a robust fallback mechanism using OANDA transactions and ensuring that only verified broker PnL is used for performance analytics and evolutionary learning.

## 1. Execution Sequence

### Step 1: Broker Layer (`core/exchange_connector.py`)
**Change:** Add `get_trade_transactions` method.
- **Logic:**
    - Call `/accounts/{account_id}/transactions` with `tradeID` filter.
    - Return the list of transactions associated with the specific trade.
    - Error handling: Return an empty list on 404 or network failure.
- **Exact Implementation:**
    ```python
    def get_trade_transactions(self, trade_id: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/accounts/{self.account_id}/transactions"
        params = {"filters": f"tradeID={trade_id}"}
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json().get('transactions', [])
            return []
        except Exception as e:
            logger.error(f"Failed to fetch transactions for trade {trade_id}: {e}")
            return []
    ```

### Step 2: Persistence Layer (`core/trade_tracker.py`)
**Change:** Update `update_outcome` to support `pnl_source`.
- **Logic:**
    - Ensure `update_outcome` accepts and stores `pnl_source` (values: "oanda" or "estimated").
    - This field will be part of the `outcome_data` dictionary passed to the method.
- **Exact Implementation:** No structural change needed to `update_outcome` as it uses `data.update(outcome_data)`, but the calling code must now provide `pnl_source`.

### Step 3: Analytics Layer (`core/analytics.py`)
**Change:** Update `calculate_performance` filter.
- **Logic:**
    - Modify the loop that processes closed trades.
    - **Strict Requirement:** Skip any trade where `t.get('pnl_source') != 'oanda'`.
    - Remove the "Virtual PnL" estimation logic (lines 34-43) from this method entirely.
- **Exact Implementation:**
    - Filter: `closed_trades = [t for t in trades if t.get('status') == 'CLOSED' and t.get('pnl_source') == 'oanda']`

### Step 4: Orchestration Layer (`live_main.py`)
**Change A:** Refactor `resolve_trade_pnl`.
- **Logic:**
    - **Primary:** Try `exchange.get_trade_details(trade_id)`. Calculate `PnL = realizedPL + financing` (using OANDA JSON paths).
    - **Fallback:** If primary fails/returns None, call `exchange.get_trade_transactions(trade_id)`. Sum the `pl` field of all `ORDER_FILL` transactions.
    - **Failure:** Return `None` instead of "TBD".
- **JSON Paths:**
    - Trade Details: `trade['realizedPL']` and `trade['financing']` (if present).
    - Transactions: `transaction['pl']` for `transaction['type'] == 'ORDER_FILL'`.

**Change B:** Update the live loop (Outcome Monitoring).
- **Logic:**
    - For real trades: Use `resolve_trade_pnl`. If result is found, record with `pnl_source: "oanda"`. If `None`, record as `pnl: None, pnl_source: "estimated"` (or similar flag) and log a warning.
    - For shadow trades: Record with `pnl_source: "estimated"`.

## 2. Verification Plan

| Test Case | Expected Result | Verification Method |
| :--- | :--- | :--- |
| **PnL Summation** | `Realized PL + Financing` matches OANDA dashboard. | Log `realizedPL` and `financing` separately before summing. |
| **Transaction Fallback** | PnL is successfully recovered from `/transactions` when `/trades` is lagging. | Mock a `None` response from `get_trade_details` and verify `get_trade_transactions` is called. |
| **Analytics Filter** | `calculate_performance` total trades count matches only those with `pnl_source == "oanda"`. | Create a test set of trades (some `oanda`, some `estimated`) and verify `total_trades` in report. |
| **Evolutionary Block** | No `estimated` PnL trades are passed to `evolver.run_evolutionary_cycle`. | Inspect `all_trades` passed to the evolver to ensure only `oanda` sources exist. |

## 3. OANDA JSON Mapping Reference

- **Trade Object (`/trades/{id}`):**
    - `realizedPL`: The actual profit/loss from the trade.
    - `financing`: The cost of carrying the position.
- **Transaction Object (`/transactions`):**
    - `type`: Must be `ORDER_FILL`.
    - `pl`: The profit/loss associated with that specific fill.

