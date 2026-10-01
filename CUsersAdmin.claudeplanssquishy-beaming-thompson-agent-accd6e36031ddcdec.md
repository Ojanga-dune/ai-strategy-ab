# Implementation Plan: Fail-Closed Handling for Zero/Unavailable Account Equity

## Root Cause
`ExchangeConnector.get_account_summary()` returns `{}` on failure. `live_main.py` then uses `float(summary.get('equity', 0))`, defaulting to `0.0`. This `0.0` is passed to `ComplianceGuard`, which interprets it as a massive drawdown relative to the start-of-day benchmark, triggering an "Emergency Shutdown" (closing all positions).

## Requirements
1. **Fail-Closed Logic**: If equity is unavailable, `None`, non-numeric, or $\le 0$, the bot must enter a 'fail-closed' state.
2. **Safe Fail**:
   - No new trades may be opened.
   - Existing positions must NOT be force-closed.
   - Log the reason and retry in the next cycle.
3. **Authoritative Source**: Use broker equity. No hardcoded defaults.
4. **Division-by-Zero**: Ensure no divisions by the benchmark in `ComplianceGuard`.
5. **Benchmark Integrity**: Daily benchmark set from correct equity and preserved, resetting only at 17:00 NY.
6. **Simulation Mode**: Maintain `simulation_mode = True` and `OANDA environment = practice`.

## Implementation Details

### 1. `core/exchange_connector.py`
Modify `get_account_summary()`:
- Change return value from `{}` to `None` when an exception occurs or the status code is not 200.
- This distinguishes between "Account exists but has 0 equity" (which should still be a dict) and "API Failure" (`None`).

### 2. `core/compliance_guard.py`
Update `check_compliance(current_equity, current_pnl)`:
- Add a check at the beginning: If `current_equity` is `None` or $\le 0$, return `(False, "Invalid Account State: Equity unavailable or invalid")`.
- Ensure the logic distinguishes between a **Violation** (Hard Stop) and an **Invalid State** (Fail-Closed).

### 3. `live_main.py`
Update the main loop (around lines 706-735):
- **Safe Equity Retrieval**:
  - Replace `float(summary.get('equity', 0))` with logic that handles `None` and `TypeError/ValueError`.
- **Conditional Compliance Update**:
  - Only call `compliance_guard.update_daily_start(equity)` and `tracker.save_equity_snapshot(equity)` if `equity` is valid ($> 0$).
- **Fail-Closed Action Logic**:
  - If `is_compliant` is `False`:
    - If the reason contains `"Invalid Account State"`, log a warning and **skip trade entries** for this cycle, but **do not** execute the emergency shutdown.
    - If the reason is a real violation (e.g., "HARD STOP"), execute the emergency shutdown (close all positions and exit/return).

### 4. Verification Plan
Create `test_compliance_fail_closed.py` to verify:
- **Scenario A: Valid Equity** $\rightarrow$ Bot continues normally.
- **Scenario B: API Failure (`None`)** $\rightarrow$ `is_compliant = False`, reason = "Invalid Account State", no new trades, no forced closures.
- **Scenario C: Zero/Negative Equity** $\rightarrow$ `is_compliant = False`, reason = "Invalid Account State", no new trades, no forced closures.
- **Scenario D: Real Drawdown** $\rightarrow$ `is_compliant = False`, reason = "HARD STOP", emergency shutdown triggered.
- **Scenario E: Benchmark Persistence** $\rightarrow$ Verify `update_daily_start` is not called with invalid data, preserving the daily benchmark.

## Critical Files
- `core/exchange_connector.py`
- `core/compliance_guard.py`
- `live_main.py`
