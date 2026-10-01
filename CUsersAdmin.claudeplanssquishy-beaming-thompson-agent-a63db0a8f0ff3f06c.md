# Implementation Plan: Commit 8 - Candle Completeness & Market Hours

## 1. Candle Completeness
**Goal**: Ensure the bot only acts on candles marked 'complete: true' by OANDA.

### Analysis
- `ExchangeConnector.get_latest_candles` already filters for `c.get('complete')` before adding to the list.
- However, `live_main.py` (line 180) uses `CandleGuard.is_candle_closed` which is a time-based estimate.
- To be strictly compliant with OANDA's 'complete' flag for the most recent candle, we should make this explicit.

### Proposed Changes
- **`core/exchange_connector.py`**:
    - Update `get_latest_candles` to return a tuple `(df, is_last_candle_complete)`.
    - `is_last_candle_complete` will be True if the last candle in the API response was marked `complete: true`.
- **`core/compliance_guard.py`**:
    - Update `CandleGuard.is_candle_closed` to accept an optional `broker_complete` boolean. If provided, it should prioritize this flag over the time-based check.
- **`live_main.py`**:
    - In `run_live_cycle`, capture the `is_last_candle_complete` flag from `exchange.get_latest_candles`.
    - Pass this flag into `candle_guard.is_candle_closed`.

---

## 2. Market Hours (Weekend Gap)
**Goal**: Prevent trading during weekends/market close gaps (Friday 17:00 to Sunday 17:00 NY time).

### Analysis
- Current `SessionFilter` uses UTC and simple weekday checks.
- Need a check for the specific NY market close window.

### Proposed Changes
- **`core/compliance_guard.py`**:
    - In `SessionFilter`, add a method `is_market_open()`.
    - Use `zoneinfo.ZoneInfo('America/New_York')` to determine current NY time.
    - **Logic**:
        - If `day == Friday` and `time >= 17:00` -> Closed.
        - If `day == Saturday` -> Closed.
        - If `day == Sunday` and `time < 17:00` -> Closed.
        - Otherwise -> Open.
    - Update `is_trade_allowed()` to first call `is_market_open()`. If the market is closed, return `(False, 'Market is closed (Weekend gap)')`.

---

## 3. Verification Plan
**Goal**: Verify the weekend gap logic without waiting for a real weekend.

### Approach: Mocking Time
- Create a test script `tests/test_market_hours.py`.
- Use `unittest.mock` to patch `datetime.datetime` and `datetime.datetime.now`.
- Test the following scenarios in `America/New_York` time:
    - **Friday 16:59**: Should be OPEN.
    - **Friday 17:01**: Should be CLOSED.
    - **Saturday 12:00**: Should be CLOSED.
    - **Sunday 16:59**: Should be CLOSED.
    - **Sunday 17:01**: Should be OPEN.
    - **Monday 09:00**: Should be OPEN.

### Critical Files for Implementation:
- `core/exchange_connector.py`
- `core/compliance_guard.py`
- `live_main.py`
