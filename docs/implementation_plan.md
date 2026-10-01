# Implementation Plan: ai-strategy-lab (Stabilization, Compliance & Optimization)

## Context
Transitioning to a professional trading bot. Priorities are safety, idempotency, and absolute synchronization with the broker.

## Execution Roadmap

### A. Live Execution Layer (Layer B) - Safety & Compliance
**1. Safety Defaults & Access**
- **Practice-by-Default**: Bot defaults to Practice endpoint.
- **Live Flag**: `LIVE_TRADING=True` required for live account access.
- **Fail Closed**: If `LIVE_TRADING` is not exactly "True", force the practice endpoint. If the account ID prefix (101- practice / 001- live) does not match the endpoint in use, abort at startup with a clear error and a Telegram alert.
- **Startup Reconciliation**: On boot, fetch all open trades/orders from OANDA. If local state and broker state mismatch, refuse to trade and send a Telegram alert.

**2. Strict Compliance Guard**
- **Bypass Removal**: Delete `is_compliant = True` and link to `compliance_guard.check_compliance()`.
- **Equity-Based Loss Check**: Use **Total Equity** (Balance + Unrealized PnL) from the account summary.
- **Dynamic Daily Reset**: Use `DAILY_RESET_TZ` (default: `America/New_York`) and `DAILY_RESET_TIME` (default: `17:00`) via `zoneinfo`.
- **Equity Snapshot**: Persist the start-of-day equity snapshot to disk.
- **Emergency Shutdown**: "Kill Switch" to cancel all pending orders and close all open positions.
- **Real-World Test**: Verify the kill-switch on a practice account with a real open position.

**3. Order Hardening & Idempotency**
- **Client ID**: Add `clientExtensions.id` to all order requests.
- **No Blind Retries**: Remove automatic `POST` retries. Classify timeouts/5xx as `UNKNOWN`.
- **Reconciliation**: Before any new order, look up the signal's `clientExtensions.id` on OANDA to see if it actually filled.
- **Response Logging**: Log the full OANDA response body (including cancel/reject reason codes) for every non-fill.
- **Circuit Breaker**: Halt bot and alert after $N=3$ consecutive real rejections. `API_UNREACHABLE` is tracked separately.
- **Idempotency Key**: Persist `(strategy, instrument, candle_timestamp)` to disk. Mark as "consumed" immediately upon order attempt.

**4. Position Counter**
- **Confirmed Sync**:
    - **Increment**: Only on confirmed `orderFillTransaction`.
    - **Decrement**: Only on confirmed close.
    - **Cycle Sync**: Re-synchronize the counter from OANDA open trades every cycle.

**B. Research & Shadow Layer (Layer A)**
**1. Data Repair**
- **Legacy Mapping**: Mark existing files as `legacy_order_id`.
- **Metric Recomputation**: Recompute per-strategy PnL, Win Rate, and RR from trade files using corrected Net PnL logic.
- **Clean Win Rate**: Reclassify phantom "CLOSED, pnl 0" files as `REJECTED` or `UNKNOWN` so they are excluded from win rate.
- **Separation**: Maintain strictly separate Live and Shadow metrics.

**2. Strategy Statistics**
- **Deep Metrics**: Compute total PnL, Win Rate, and RR (Avg Win / Avg Loss) from records. Include trade count.

**3. Backtester Realism**
- **Slippage/Spread**: Implement per-instrument spread and slippage modeling in `core/backtester.py`.

**4. Controlled Evolver**
- **Separate Process**: Move `run_evolutionary_cycle()` to a separate scheduled job (not in `live_main.py`).
- **Shadow-Only**: Run only for shadow strategies after Data Repair is finished.
- **Manual Promotion**: Champion promotion requires:
    1. Min trade count (e.g., 30 trades).
    2. Out-of-sample validation.
    3. **Telegram Approval Request** (No automatic promotion).

**C. General Enhancements**
- **Candle Guard**: Strictly use `complete: true` candles only.
- **Market Hours**: Implement weekend/market-closed handle.
- **Telegram Updates**:
    - Add: Startup/Shutdown, Heartbeat, Blocked-Signal alerts (with reason).
    - Enhance: Include strategy name, RR, and duration in closed-trade messages.
    - Daily Report: Include PnL, Win Rate, and RR per strategy.
- **Archive Strategy**: Move closed trades to archive; **do not delete**.

## Implementation Sequence (Ordered Commits)

| Order | Layer | File | Function | Change | Test/Proof | Risk |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | B | `live_main.py` | `main()` | Practice default / Live flag / ID mismatch abort | Verify connection to Practice / ID mismatch fail | Low |
| 2 | B | `live_main.py` | `main()` | Remove `is_compliant` bypass | Mock violation $\rightarrow$ Shutdown | Low |
| 3 | B | `compliance_guard.py` | `check_compliance` | Equity-based check + DST Reset | DST transition test | Low |
| 4 | B | `live_main.py` | `main()` | Persist start-of-day equity snapshot | Restart bot $\rightarrow$ Check snapshot | Low |
| 5 | B | `live_main.py` | `main()` | Real practice-account kill-switch test | Open position $\rightarrow$ Kill $\rightarrow$ Verify close | Medium |
| 6 | B | `live_main.py` | `main()` | Startup reconciliation mismatch alert | Force mismatch $\rightarrow$ Bot refuses trade | Medium |
| 7 | B | `exchange_connector.py`| `place_market_order`| Add `clientExtensions.id` | Inspect OANDA request payload | Low |
| 8 | B | `live_main.py` | `run_live_cycle` | `complete:true` candles + Market hours | Mock weekend $\rightarrow$ Bot pauses | Low |
| 9 | B | `live_main.py` | `run_live_cycle` | Remove blind `POST` retries + ID lookup check | Mock 500 error $\rightarrow$ Verify no blind retry + ID lookup | Low |
| 10 | B | `live_main.py` | `run_live_cycle` | Position counter (Sync $\rightarrow$ Inc $\rightarrow$ Dec) | 2 signals in 1 cycle $\rightarrow$ Verify cap | Medium |
| 11 | B | `live_main.py` | `run_live_cycle` | Idempotency key + Circuit Breaker | Trigger 3 rejects $\rightarrow$ Bot halts | Medium |
| 12 | A | `core/backtester.py` | `run` | Add spread/slippage modeling | Compare backtest vs live PnL | Medium |
| 13 | A | `core/evolver.py` | `run_cycle` | Separate process + Manual promo + Data backup | Backup data/ $\rightarrow$ Dry-run report $\rightarrow$ Update | Low |
| 14 | B | `notifications.py` | `send_sync` | Add Heartbeat/Startup/Blocked alerts | Trigger blocked signal $\rightarrow$ Check TG | Low |
| 15 | B | `live_main.py` | `main()` | Archive closed trades (no delete) | Low |
| 16 | B | `live_main.py` | `main()` | Real practice kill-switch test | Open position $\rightarrow$ Kill $\rightarrow$ Verify close | Medium |
