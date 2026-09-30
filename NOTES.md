# Project Notes: ai-strategy-lab Stabilization & PnL Fixes

## Root Cause: 'TBD' PnL Bug
- **Cause**: Bot used internal sequential IDs (e.g., '16') instead of OANDA Trade IDs for lookups.
- **API Issue**: OANDA v20 API does not have a 'pnl' key; it uses 'realizedPL' and 'financing'.
- **Effect**: Lookups returned 404 -> Bot recorded 'TBD'.

## Implementation: Robust PnL Resolution
- **Primary Path**: `realizedPL + financing` from /trades/{id}.
- **Fallback Path**: Recursive pagination of /transactions filtered by tradeID, summing 'pl' of 'ORDER_FILL' events.
- **Provenance**: Added 'pnl_source' ('oanda' vs 'estimated').
- **Analytics**: strictly filters for 'pnl_source == oanda' to protect strategy evolution and champion promotion.

## Known Issues & State
- **ID Mismatch**: Old trades in data/trades/ use local indices; new trades use OANDA IDs.
- **Sync**: Bot state sometimes drifts from broker; reconciled on startup.
- **0.0 Trades**: Many old trades recorded as 0.0, polluting win-rate stats.

## Critical Paths
- `ExchangeConnector.get_trade_transactions` -> handles pagination for fallback PnL.
- `resolve_trade_pnl` (live_main.py) -> orchestration of Primary -> Fallback -> None.
- `Analytics.calculate_performance` -> filtered by pnl_source.
