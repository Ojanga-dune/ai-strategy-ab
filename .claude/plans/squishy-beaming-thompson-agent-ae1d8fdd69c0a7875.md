# Implementation Plan: Complete Candles + Market Hours

## Requirements
1. **Candle Completeness**: Ensure the bot only acts on candles marked `complete: true` by OANDA.
2. **Market Hours**: Prevent trading during weekends/market close gaps (Friday 17:00 to Sunday 17:00 NY time).

## Analysis
- `ExchangeConnector.get_latest_candles` already filters for `if c.get('complete'):`. DataFrames returned only contain completed candles.
- `live_main.py` uses `CandleGuard.is_candle_closed` (a time-based heuristic), which is now redundant and potentially conflicting with the API's `complete` flag.
- `SessionFilter` in `core/compliance_guard.py` uses `datetime.utcnow()`, which is insufficient for handling the specific New York time gap (Friday 17:00 to Sunday 17:00).

## Proposed Changes

### 1. Candle Completeness
- **File**: `live_main.py`
- **Modification**: Remove the `CandleGuard.is_candle_closed` check within `run_live_cycle`.
- **Rationale**: The `ExchangeConnector` already guarantees that any candle in the returned DataFrame is marked `complete` by the broker. Relying on the broker's flag is more accurate than a local timer.

### 2. Market Hours
- **File**: `core/compliance_guard.py`
- **Modification**:
    - Update `SessionFilter` to use `zoneinfo.ZoneInfo("America/New_York")`.
    - Implement `is_market_open()` logic:
        - Market is **CLOSED** if:
            - Day is Friday AND time is $\ge$ 17:00 NY.
            - Day is Saturday.
            - Day is Sunday AND time is $<$ 17:00 NY.
    - Integrate `is_market_open()` check into `is_trade_allowed()`.
- **Rationale**: Precise adherence to market close times prevents trying to enter trades during gaps where liquidity is zero or spreads are extreme.

## Detailed Implementation Steps

### Step 1: Update `core/compliance_guard.py`
1. Import `ZoneInfo` (already present via `zoneinfo` try/except).
2. Modify `SessionFilter.is_trade_allowed()`:
    - Replace `datetime.utcnow()` with `datetime.now(zoneinfo.ZoneInfo("America/New_York"))`.
    - Add a helper method `_is_market_open(now_ny: datetime) -> bool`:
        - `weekday = now_ny.weekday()` (0=Mon, 4=Fri, 5=Sat, 6=Sun).
        - `current_time = now_ny.time()`.
        - If `weekday == 4` and `current_time >= time(17, 0)`, return `False`.
        - If `weekday == 5`, return `False`.
        - If `weekday == 6` and `current_time < time(17, 0)`, return `False`.
        - Otherwise, return `True`.
    - In `is_trade_allowed()`, call `_is_market_open()` first. If `False`, return `(False, "Market is closed for the weekend.")`.

### Step 2: Update `live_main.py`
1. In `run_live_cycle`, remove:
   ```python
   if not candle_guard.is_candle_closed(last_candle_time, gran_seconds):
       logger.info(f"CandleGuard: Current candle is still forming. Waiting for close.")
       return
   ```
2. Remove `candle_guard` from the `run_live_cycle` arguments and the call site in `main()`.

## Verification Plan
- **Unit Test for Market Hours**:
    - Create a test case using `unittest.mock.patch` on `datetime.datetime`.
    - Mock time to:
        - Friday 16:59 NY $\rightarrow$ Expected: Open.
        - Friday 17:01 NY $\rightarrow$ Expected: Closed.
        - Saturday 12:00 NY $\rightarrow$ Expected: Closed.
        - Sunday 16:59 NY $\rightarrow$ Expected: Closed.
        - Sunday 17:01 NY $\rightarrow$ Expected: Open.
- **Integration Check**:
    - Verify logs in `live_main.py` no longer show "CandleGuard: Current candle is still forming" but still process data from `ExchangeConnector`.

## Critical Files
- `core/compliance_guard.py`
- `live_main.py`
EOF`
