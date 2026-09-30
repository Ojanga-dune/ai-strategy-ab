# Project Stabilization Tasks

## RULES
- The bot is STOPPED. Never start it. Never place real orders. No order endpoint calls at all, except the final verification task.
- Bug fixes only. No new features, assets, or "prop-firm" extras beyond the tasks below.
- One task at a time. Use the edit tool so the user sees each diff. 
- After each task: show `git diff --stat`, run a test that uses a mocked connector and no network, and paste the real output.
- Stop and wait for approval before the next task.
- Never say "fixed" or "verified" without test output. Label anything else UNVERIFIED.
- Never print tokens or keys. Show only the last 4 digits of account IDs.
- Keep PROGRESS.md updated: DONE / VERIFIED / UNVERIFIED per task.

## TASKS
0. git init if needed and commit a baseline. Make sure .env is in .gitignore. Set logging.getLogger("httpx") to WARNING so request URLs (and tokens) are never logged.
1. Order retry cap. Success means orderFillTransaction is present; an orderCancelTransaction or orderRejectTransaction is a failure. Max 3 retries. Retry only network errors, 5xx and 429. Never retry other 4xx. Before retrying after a timeout or 5xx, check that the earlier order did not fill. error_code must be the integer HTTP status. On final failure save a REJECTED record with the HTTP status and full response body (no tokens), and send a Telegram alert wrapped in try/except.
2. Order/trade ID fix. Keep order_id and trade_id as separate fields. trade_id comes from orderFillTransaction.tradeOpened.tradeID (use the fill in the order response first, and poll only as a backup). Handle tradesClosed and tradeReduced. Use a stable local ID for the filename, not an OANDA ID. No renames.
3. Per-trade PnL. resolve_trade_pnl must use tradesClosed[].realizedPL for THIS trade's ID, never a fill's top-level pl, and never sum unrelated fills. Remove the fake tradeID query parameter. First confirm from the code whether financing and commission are already included. Handle pnl=None everywhere (analytics, registry).
4. Max open positions cap (config, default 1). Show what the current behaviour is when a signal arrives while a position is open.
5. Freeze PostMortemAgent (config flag, default OFF). Move shadow trades to data/shadow_trades/ so they never touch analytics or StrategyRegistry.
6. Staleness and timing. Act only on the most recently closed candle. Replace sleep(3600) with sleeping until the next candle close plus 5 seconds.
7. Precision. Fetch displayPrecision from /instruments and send SL/TP as strings rounded to it.
8. Compliance guard. Daily benchmark resets once per date change; the reset time is a config value, default midnight EAT. Remove the is_compliant = True bypass and link it to check_compliance. Test the shutdown path with unit tests and a mocked connector ONLY.
9. calculate_account_daily_pnl(): ORDER_FILL events only, pl + financing + commission, paginated, since the configured day start. The daily report shows verified trades vs rejected orders.
10. Data. COPY data/trades/ to an archive folder. Do not delete or move the originals, and do not touch StrategyRegistry stats. Then a DRY RUN backfill table for files that are real OANDA orders (order -> tradeOpened.tradeID -> realizedPL). Write nothing.
11. Read-only diagnostics, using GET /transactions/{id} and /transactions/idrange (not /positions): how trades 136 and 144 closed; the cancel or reject reason for each cancelled order (files 158-189); the recorded_at time of files 171-189.
12. Write verify_one_trade.py: one minimum-size practice order, then print order_id, trade_id, the SL and TP order IDs on the trade, then close it and print realizedPL. Do NOT run it.
