# Implementation Plan: Fail-Closed Handling for Zero or Unavailable Account Equity

## Objective
Fix a critical bug where `ExchangeConnector.get_account_summary()` returns an empty dictionary `{}` on failure, and `live_main.py` defaults `equity` to `0.0` using `.get('equity', 0)`. This causes a false 'Total Loss' scenario, triggering an Emergency Shutdown and closing all positions.

## Requirements
1. **Fail-Closed Logic**: If equity is unavailable, `None`, non-numeric, or `<= 0`, the bot must enter a 'fail-closed' state.
2. **Safe Fail**:
   - No new trades may be opened.
   - Existing positions must NOT be force-closed.
   - Log the reason and retry in the next cycle.
3. **Authoritative Source**: Use broker equity; no hardcoded defaults.
4. **Division-by-Zero**: Ensure no divisions by the benchmark in `ComplianceGuard`.
5. **Benchmark Integrity**: Preserve daily benchmark until 17:00 NY boundary.
6. **Simulation Mode**: Maintain `simulation_mode = True` and `OANDA environment = practice`.

## Implementation Strategy

### 1. `core/exchange_connector.py`
- Modify `get_account_summary()`:
  - Instead of returning `{}` on failure (lines 144, 147), return `None`.
  - Ensure the return type is `Optional[Dict[str, Any]]`.

### 2. `live_main.py`
- **Main Loop Update (around line 705)**:
  - Replace `equity = float(summary.get('equity', 0))` and `balance = float(summary.get('balance', 0))` with logic that handles `summary is None`.
  - If `summary` is `None` or `equity` is missing/invalid/`<= 0`:
    - Log a warning: `Equity unavailable or invalid. Entering fail-closed mode for this cycle.`
    - Skip `compliance_guard.update_daily_start(equity)`, `tracker.save_equity_snapshot(equity)`, and `compliance_guard.check_compliance(...)`.
    - Skip the `run_live_cycle` loop for all assets (prevents new trades).
    - **Allow** `manage_active_trades` to continue (monitoring existing positions).
- **Safe Transition**: Ensure that when `equity` is invalid, we do NOT call `compliance_guard.check_compliance` because that function would interpret `current_equity=0` as a massive drawdown relative to `start_of_day_equity`, triggering the Emergency Shutdown.

### 3. `core/compliance_guard.py`
- **`update_daily_start(equity)`**:
  - Add validation: if `equity is None` or `equity <= 0`, do NOT update `self.start_of_day_equity`.
- **`check_compliance(current_equity, current_pnl)`**:
  - Add a guard clause at the beginning: if `current_equity is None` or `current_equity <= 0`, return `(True, "Equity unavailable - skipping compliance check")` or similar, to prevent triggering a false failure.
  - Verify no divisions by `self.start_of_day_equity` exist (currently it uses subtraction for drawdown: `self.start_of_day_equity - current_equity`, which is safe from div-by-zero).

## Verification Plan

### Mocked Tests
1. **Valid Positive Equity**: Ensure bot operates normally.
2. **Equity = 0**: Verify bot skips trade entry and compliance checks but does NOT close positions.
3. **Equity = None**: Verify bot skips trade entry and compliance checks.
4. **Malformed Response**: (e.g., `summary = {'balance': 'abc'}`) Verify graceful handling.
5. **Broker Timeout**: `get_account_summary` returns `None`, bot enters fail-closed mode for one cycle.
6. **Benchmark Persistence**: Verify `start_of_day_equity` remains constant across cycles where equity is unavailable.

## Critical Files for Implementation
- `core\exchange_connector.py`
- `live_main.py`
- `core\compliance_guard.py`
