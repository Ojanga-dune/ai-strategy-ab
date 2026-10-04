import time
import logging
import os
import threading
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any

# Silence httpx request logging to prevent tokens/URLs from leaking in logs
import logging as py_logging
py_logging.getLogger("httpx").setLevel(py_logging.WARNING)

from core.config import settings
from core.datalake import DataLake
from core.strategy_engine import StrategyEngine
from core.ai_reviewer import AIReviewer
from core.exchange_connector import ExchangeConnector
from core.risk_manager import RiskManager
from core.notifications import NotificationManager
from core.trade_tracker import TradeTracker
from core.strategy_registry import StrategyRegistry
from core.backtester import ParallelBacktester
from core.analytics import Analytics
from architect.post_mortem import PostMortemAgent
from architect.strategist import StrategistAgent
from core.portfolio_manager import PortfolioManager
from core.compliance_guard import ComplianceGuard, SessionFilter, CandleGuard
from core.state_manager import StateManager
from core.news_guard import NewsGuard
from core.signal_tracker import SignalTracker
from core.circuit_breaker import CircuitBreaker
from core.runtime_state import BotRuntimeState

# Load environment variables
# Now handled by core.config.settings singleton

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LiveBot")

def flatten_broker_trade_ids(positions: List[Dict[str, Any]]) -> set:
    """
    Extracts all active broker trade IDs from the aggregated OANDA position response.
    """
    if positions is None:
        return set()

    all_ids = set()
    for pos in positions:
        long_ids = pos.get('long', {}).get('tradeIDs', [])
        if isinstance(long_ids, list):
            all_ids.update(long_ids)

        short_ids = pos.get('short', {}).get('tradeIDs', [])
        if isinstance(short_ids, list):
            all_ids.update(short_ids)

    return all_ids

def resolve_trade_pnl(exchange: ExchangeConnector, trade_id: str, retries: int = 5, delay: int = 10) -> Optional[float]:
    """
    Attempts to fetch the final PnL of a closed trade.
    Primary: Use /trades/{tradeID} -> realizedPL + financing.
    """
    for i in range(retries):
        try:
            trade_details = exchange.get_trade_details(trade_id)
            if trade_details:
                realized = trade_details.get('realizedPL', 0)
                financing = trade_details.get('financing', 0)

                try:
                    total_pnl = float(realized) + float(financing)
                    logger.info(f"Net PnL resolved via Trade Details for {trade_id}: {total_pnl:.2f}")
                    return total_pnl
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to cast PnL fields for {trade_id}: {realized}, {financing}. Error: {e}")

        except Exception as e:
            logger.error(f"Unexpected error resolving PnL for {trade_id}: {e}")

        if i < retries - 1:
            logger.info(f"Trade {trade_id} PnL not yet resolved. Retry {i+1}/{retries} in {delay}s...")
            time.sleep(delay)

    return None

def manage_active_trades(exchange: ExchangeConnector, tracker: TradeTracker, notifier: NotificationManager, instrument: str):
    """
    SAFE COORDINATOR: Reconciles local trade state with broker positions.
    Does NOT implement automated trading rules (BE, Trailing, etc.) as none are defined.
    Delegates closure detection and recording to monitor_trade_outcomes.
    """
    try:
        local_open = tracker.get_open_trades()

        try:
            broker_positions = exchange.get_open_positions(instrument)
            if broker_positions is None:
                raise ValueError("Broker API returned None (Failure)")
        except Exception as e:
            logger.error(f"Broker query failed for {instrument}: {e}. Skipping active management to prevent erroneous closures.")
            return

        active_ids = flatten_broker_trade_ids(broker_positions)

        logger.info(f"Active Management [{instrument}]: Local Trades: {len(local_open)}, Broker Trade IDs: {len(active_ids)}")

        monitor_trade_outcomes(exchange, tracker, notifier, StrategyRegistry(), MONITORED_ASSETS, active_ids)

    except Exception as e:
        logger.error(f"Error in manage_active_trades for {instrument}: {e}")

def monitor_trade_outcomes(exchange: ExchangeConnector, tracker: TradeTracker, notifier: NotificationManager, registry: StrategyRegistry, monitored_assets: List[Dict], active_broker_ids: set = None):
    """
    Checks for closed trades and updates their outcomes.
    """
    open_trades = tracker.get_open_trades()
    if not open_trades:
        return

    if active_broker_ids is None:
        broker_pos = exchange.get_open_positions()
        if broker_pos is None:
            logger.warning("Outcome monitor: Broker positions unavailable. Skipping closure checks.")
            return
        active_broker_ids = flatten_broker_trade_ids(broker_pos)

    logger.info(f"Monitoring {len(open_trades)} open trades for outcomes...")

    current_prices = {}
    for asset in monitored_assets:
        instrument = asset['symbol']
        candles = exchange.get_latest_candles(instrument, "M1", count=1)
        if not candles.empty:
            current_prices[instrument] = candles.iloc[-1]['close']

    for trade in open_trades:
        t_local_id = trade['local_id']
        t_trade_id = trade.get('trade_id')
        t_order_id = trade.get('order_id')

        if trade.get('is_simulated', False):
            instrument = trade.get('instrument')
            if instrument not in current_prices: continue
            current_price = current_prices[instrument]

            entry_price = trade.get('entry_price')
            sl = trade.get('sl')
            tp = trade.get('tp')
            strat_version = trade.get('strategy_version')
            if sl is None or tp is None: continue

            is_long = tp > entry_price
            closed = False
            pnl = 0.0
            reason = ""
            if is_long:
                if current_price <= sl: closed, pnl, reason = True, sl - entry_price, "SL Hit"
                elif current_price >= tp: closed, pnl, reason = True, tp - entry_price, "TP Hit"
            else:
                if current_price >= sl: closed, pnl, reason = True, entry_price - sl, "SL Hit"
                elif current_price <= tp: closed, pnl, reason = True, entry_price - tp, "TP Hit"

            if closed:
                logger.info(f"Shadow Trade {t_local_id} virtually closed ({reason}). PnL: {pnl:.3f}")
                tracker.update_outcome(t_local_id, {"status": "CLOSED", "pnl": pnl, "pnl_source": "estimated", "reason": reason})
                registry.update_performance(instrument, strat_version, pnl, pnl > 0, pnl_source="estimated")
                notifier.send_sync(f"👻 Shadow Trade {strat_version} closed: {reason} (PnL: {pnl:.3f})")
            continue

        if not t_trade_id and t_order_id:
            logger.info(f"Resolving missing TradeID for {t_local_id} using OrderID {t_order_id}...")
            resolved_trade_id = exchange.get_trade_id_from_order(t_order_id)
            if resolved_trade_id:
                logger.info(f"Resolved TradeID: {resolved_trade_id} for {t_local_id}")
                tracker.update_outcome(t_local_id, {"trade_id": resolved_trade_id, "status": "OPEN"})
                t_trade_id = resolved_trade_id
            else:
                logger.warning(f"Trade {t_local_id} still lacks a valid TradeID. Retrying next cycle.")
                continue

        if not t_trade_id:
            logger.warning(f"Trade {t_local_id} has no OANDA TradeID and cannot be reconciled. Skipping.")
            continue

        if t_trade_id in active_broker_ids:
            continue

        logger.info(f"Trade {t_trade_id} (Local: {t_local_id}) missing from active positions. Verifying closure...")
        trade_details = exchange.get_trade_details(t_trade_id)

        if trade_details is None:
            logger.warning(f"Trade {t_trade_id} details unavailable (API failure). Preserving OPEN state.")
            continue

        realized_pnl = resolve_trade_pnl(exchange, t_trade_id)
        if realized_pnl is not None:
            tracker.update_outcome(t_local_id, {"status": "CLOSED", "pnl": realized_pnl, "pnl_source": "oanda"})
            notifier.send_sync(f"🏁 Trade Closed: {t_trade_id}. PnL: {realized_pnl:.2f}")
        else:
            logger.warning(f"Trade {t_trade_id} closure confirmed, but PnL resolution failed. Retrying next cycle.")

def run_live_cycle(
    instrument: str,
    granularity: str,
    exchange: ExchangeConnector,
    engine: StrategyEngine,
    reviewer: AIReviewer,
    risk_manager: RiskManager,
    datalake: DataLake,
    notifier: NotificationManager,
    tracker: TradeTracker,
    registry: StrategyRegistry,
    session_filter: SessionFilter,
    candle_guard: CandleGuard,
    news_guard: NewsGuard,
    signal_tracker: SignalTracker,
    circuit_breaker: CircuitBreaker,
    orchestrator: Any
):
    """
    A single iteration of the Live Loop:
    Live Data -> Sieve -> Brain -> Guard -> Execute
    """
    logger.info(f"--- Starting Live Cycle for {instrument} {granularity} ---")

    try:
        allowed, session_msg = session_filter.is_trade_allowed()
        if not allowed:
            logger.info(f"Session Filter: {session_msg}. Skipping cycle.")
            return

        news_allowed, news_msg = news_guard.is_news_event_active(exchange.api_key, exchange.account_id)
        if news_allowed:
            logger.info(f"NewsGuard: {news_msg}. Skipping cycle.")
            return

        df = exchange.get_latest_candles(instrument, granularity, count=200)
        if df.empty:
            logger.warning("No live data fetched. Skipping cycle.")
            return

        last_candle_time = df.index[-1]
        gran_map = {'H4': 14400, 'H1': 3600, 'M30': 1800, 'M15': 900, 'M5': 300, 'M1': 60}
        gran_seconds = gran_map.get(granularity, 3600)

        df = datalake._calculate_indicators(df)
        strategies = registry.get_all_strategies(instrument)

        for strat in strategies:
            is_champion = strat.get("is_champion", False)
            strat_version = strat["version"]

            strategy_config = {
                'version': strat['version'],
                'instrument': instrument,
                'granularity': granularity,
                'rules': strat['rules']
            }

            class LiveDataMock:
                def load_data(self, inst, gran): return df

            candidates = engine.find_candidates(strategy_config, LiveDataMock())
            if not candidates:
                logger.info(f"Sieve ({strat_version}): No candidates found.")
                continue

            logger.info(f"Sieve ({strat_version}): Found {len(candidates)} candidates. Passing to AI Reviewer...")

            reviewer_mock = LiveDataMock()
            mtf_granularities = ['H4', 'H1', 'M30', 'M15', 'M5', 'M1']
            mtf_data = exchange.get_mtf_candles(instrument, mtf_granularities, count=200)
            for gran in mtf_data:
                mtf_data[gran] = datalake._calculate_indicators(mtf_data[gran])
            confluence = engine.evaluate_confluence(mtf_data)

            if not confluence.get('regime_filter_passed', True):
                logger.info(f"Regime Filter Blocked: {confluence.get('regime_status')} - Skipping candidates.")
                continue

            verified_trades = reviewer.validate_signals(candidates, reviewer_mock, confluence=confluence)

            if not verified_trades:
                logger.info(f"Brain ({strat_version}): No candidates approved.")
                continue

            verified_trades = sorted(verified_trades, key=lambda x: x['timestamp'], reverse=True)
            latest_trade = verified_trades[0]

            now = datetime.now(latest_trade['timestamp'].tzinfo)
            time_diff = now - latest_trade['timestamp']

            if time_diff.total_seconds() > 86400:
                logger.info(f"Brain ({strat_version}): Latest signal too old. Skipping.")
                continue

            if is_champion:
                logger.info(f"Champion ({strat_version}) approved a trade. Proceeding to Execution Guard...")

                all_open_positions = exchange.get_open_positions()
                if len(all_open_positions) >= MAX_OPEN_POSITIONS:
                    logger.warning(f"Guard: Trade blocked. Global position cap reached ({len(all_open_positions)}/{MAX_OPEN_POSITIONS}).")
                    continue

                summary = exchange.get_account_summary()
                balance = float(summary.get('balance', 0))
                equity = float(summary.get('equity', 0))
                start_of_day_balance = balance

                positions = exchange.get_open_positions(instrument)
                allowed, reason = risk_manager.can_trade(positions, balance, start_of_day_balance)

                if not allowed:
                    logger.warning(f"Guard: Trade blocked. Reason: {reason}")
                    continue

                current_atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else 2.0
                sl_dist = current_atr * 1.5
                tp_dist = current_atr * 3.0

                is_bullish = "bullish" in latest_trade.get('ai_reasoning', '').lower()
                sl_price = latest_trade['price'] - sl_dist if is_bullish else latest_trade['price'] + sl_dist
                tp_price = latest_trade['price'] + tp_dist if is_bullish else latest_trade['price'] + tp_dist

                lots = risk_manager.calculate_position_size(
                    account_balance=balance,
                    entry_price=latest_trade['price'],
                    stop_loss=sl_price,
                    instrument=instrument
                )
                side_lots = lots if is_bullish else -lots

                max_retries = 3
                retry_delay = 2
                result = None
                consecutive_rejections = 0

                client_id = f"sig_{strat_version}_{instrument}_{int(latest_trade['timestamp'].timestamp())}"

                if signal_tracker.is_consumed(strat_version, instrument, latest_trade['timestamp'].timestamp()):
                    logger.info(f"Signal {client_id} already consumed. Skipping to prevent repeated attempts.")
                    continue

                if exchange.check_order_exists(client_id):
                    logger.warning(f"Order {client_id} already exists on OANDA. Skipping to prevent double-fill.")
                    tracker.record_entry(client_id, {"status": "CONSUMED", "reason": "Duplicate ID found on broker"})
                    signal_tracker.mark_consumed(strat_version, instrument, latest_trade['timestamp'].timestamp())
                    continue

                for attempt in range(max_retries):
                    logger.info(f"Executing Champion Order (Attempt {attempt+1}/{max_retries}): {instrument} {side_lots} lots (CID: {client_id})...")
                    result = exchange.place_market_order(
                        instrument=instrument,
                        lots=side_lots,
                        stop_loss=sl_price,
                        take_profit=tp_price,
                        client_id=client_id
                    )

                    if result and (result.get('status') == 'success' or 'orderFillTransaction' in result):
                        break

                    error_code = result.get('error_code') if result else None
                    if error_code is not None:
                        try:
                            code = int(error_code)
                            if 400 <= code < 500 and code != 429:
                                logger.warning(f"Non-retryable error {code}: {result.get('message', 'Unknown error')}. Stopping retries.")
                                break
                        except (ValueError, TypeError):
                            logger.warning(f"Order rejected with non-integer error code {error_code}: {result.get('message', 'Unknown error')}. Stopping retries.")
                            break
                    else:
                        if result and result.get('status') == 'error':
                            break

                    if attempt < max_retries - 1:
                        logger.warning(f"Order attempt {attempt+1} failed (Code: {error_code}). Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)

                if not result or (result.get('status') == 'error' and 'orderFillTransaction' not in (result or {})):
                    error_status = result.get('error_code', 'UNKNOWN') if result else 'NETWORK_ERROR'
                    full_response = result if result else 'No response'
                    if isinstance(full_response, dict) and 'token' in full_response:
                        full_response = {k: v for k, v in full_response.items() if k != 'token'}

                    reject_record = {
                        'instrument': instrument,
                        'lots': side_lots,
                        'status': 'REJECTED',
                        'error_code': error_status,
                        'response': full_response,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }

                    temp_id = (result or {}).get('orderCreateTransaction', {}).get('id', f"rejected_{int(time.time())}")
                    tracker.record_entry(temp_id, reject_record)

                    signal_tracker.mark_consumed(strat_version, instrument, latest_trade['timestamp'].timestamp())

                    tripped, reason = circuit_breaker.record_rejection()
                    if tripped:
                        notifier.send_sync(f"🚨 **CIRCUIT BREAKER TRIPPED**\n{reason}\nTrading halted for this account.")
                        logger.critical(reason)

                    try:
                        notifier.send_sync(f"🚨 **Order Rejected**\nInstrument: {instrument}\nStatus: {error_status}\nError: {result.get('message', 'Unknown error') if result else 'Network Error'}")
                    except Exception as e:
                        logger.error(f"Failed to send Telegram alert for rejected order: {e}")

                    continue

                if 'orderCreateTransaction' in result:
                    order_id = result['orderCreateTransaction']['id']

                    trade_id = None
                    if 'orderFillTransaction' in result:
                        fill = result['orderFillTransaction']
                        if 'tradeOpened' in fill:
                            trade_id = fill['tradeOpened'].get('tradeID')

                    local_id = f"trade_{int(time.time())}_{order_id}"

                    trade_dna = {
                        'order_id': order_id,
                        'trade_id': trade_id,
                        'instrument': instrument,
                        'entry_price': latest_trade['price'],
                        'units': side_lots,
                        'sl': sl_price,
                        'tp': tp_price,
                        'ai_reasoning': latest_trade.get('ai_reasoning'),
                        'timestamp': latest_trade['timestamp'].isoformat() if hasattr(latest_trade['timestamp'], 'isoformat') else latest_trade['timestamp'],
                        'strategy_version': strat_version,
                        'status': 'OPEN' if trade_id else 'PENDING_TRADE_ID'
                    }
                    tracker.record_entry(local_id, trade_dna)

                if 'orderCancelTransaction' in result:
                    cancel_reason = result['orderCancelTransaction'].get('reason', 'Unknown')
                    error_msg = f"❌ Trade Cancelled: {cancel_reason}\n\n💡 How to fix: This usually happens if the market is halted or the order was too large for current liquidity. Try reducing risk or check OANDA server status."
                    notifier.send_sync(error_msg)
                    if 'orderCreateTransaction' in result:
                        order_id = result['orderCreateTransaction']['id']
                        local_id = f"trade_{int(time.time())}_{order_id}"
                        tracker.update_outcome(local_id, {"status": "CLOSED", "pnl": 0, "reason": "Cancelled"})
                elif result.get('status') == 'error':
                    error_msg = f"❌ Order Error: {result.get('message')}\n\n💡 Details: {result.get('raw')}"
                    notifier.send_sync(error_msg)
                    if 'orderCreateTransaction' in result:
                        order_id = result['orderCreateTransaction']['id']
                        local_id = f"trade_{int(time.time())}_{order_id}"
                        tracker.update_outcome(local_id, {"status": "CLOSED", "pnl": 0, "reason": "Cancelled"})
                elif result.get('status') == 'success' or 'orderCreateTransaction' in result:
                    dir_text = "LONG 📈" if side_lots > 0 else "SHORT 📉"
                    exec_msg = (
                        f"✅ Champion {strat_version} executed {dir_text}!\n"
                        f"Instrument: {instrument}\n"
                        f"Entry: {latest_trade['price']:.3f}\n"
                        f"TP: {tp_price:.3f}\n"
                        f"SL: {sl_price:.3f}\n"
                        f"Lots: {abs(side_lots)}"
                    )
                    notifier.send_sync(exec_msg)
                else:
                    fail_msg = "❌ Champion failed execution.\n\n💡 How to fix: Check if your API key is still valid or if you have enough margin for this trade size."
                    notifier.send_sync(fail_msg)
            else:
                logger.info(f"Challenger ({strat_version}) approved a trade. Recording in Shadow Mode...")
                current_atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else 2.0
                sl_dist = current_atr * 1.5
                tp_dist = current_atr * 3.0
                is_bullish = "bullish" in latest_trade.get('ai_reasoning', '').lower()
                sl_price = latest_trade['price'] - sl_dist if is_bullish else latest_trade['price'] + sl_dist
                tp_price = latest_trade['price'] + tp_dist if is_bullish else latest_trade['price'] + tp_dist

                shadow_trade_id = f"shadow_{strat_version}_{latest_trade['timestamp'].timestamp()}"
                trade_dna = {
                    'instrument': instrument,
                    'entry_price': latest_trade['price'],
                    'units': 1.0,
                    'sl': sl_price,
                    'tp': tp_price,
                    'ai_reasoning': latest_trade.get('ai_reasoning'),
                    'timestamp': latest_trade['timestamp'].isoformat(),
                    'strategy_version': strat_version,
                    'is_simulated': True
                }
                tracker.record_entry(shadow_trade_id, trade_dna)
                logger.info(f"Shadow trade recorded for {strat_version}: {shadow_trade_id}")

    except Exception as e:
        logger.error(f"Error during live cycle for {instrument}: {e}", exc_info=True)

def cmd_positions(text, context, exchange):
    positions = exchange.get_open_positions()
    if not positions:
        return "No open positions."
    msg = "📈 **Open Positions**\n\n"
    for p in positions:
        inst = p.get('instrument', 'Unknown')
        units = p.get('long', {}).get('units', 0) if p.get('long', {}).get('units') != '0' else p.get('short', {}).get('units', 0)
        pl = p.get('unrealizedPL', '0.0')
        avg_price = p.get('long', {}).get('averagePrice', p.get('short', {}).get('averagePrice', 'N/A'))
        msg += f"🔸 {inst} | Units: {units} | Price: {avg_price} | PnL: ${pl}\n"
    return msg

def cmd_close_all(text, context, exchange):
    positions = exchange.get_open_positions()
    if not positions:
        return "No open positions to close."
    for p in positions:
        inst = p.get('instrument', 'XAU_USD')
        units = float(p.get('long', {}).get('units', 0)) - float(p.get('short', {}).get('units', 0))
        if units != 0:
            exchange.place_market_order(inst, -units)
    return "✅ Sent close orders for all positions."

def cmd_close_partial(text, context, exchange):
    try:
        parts = text.split()
        if len(parts) < 3:
            return "❌ Usage: /close_partial <instrument> <units> (e.g., /close_partial XAU_USD 50)"
        instrument = parts[1]
        units_to_close = int(parts[2])
        result = exchange.place_market_order(instrument, -units_to_close)
        if 'orderCreateTransaction' in result:
            return f"✅ Partially closed {abs(units_to_close)} units of {instrument}."
        return f"❌ Failed to partial close: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def cmd_move_be(text, context):
    return "🛠️ Move to Break Even is automated in the loop. Manual trigger not available."

def cmd_daily(text, context, tracker, registry):
    all_trades = tracker.get_all_trades()
    stats = Analytics().calculate_performance(all_trades)
    champ_stats = "No Champion active"
    champ = registry.get_champion("XAU_USD")
    if champ:
        perf = champ.get('performance', {})
        win_rate = perf.get('win_rate', '0%')
        total_trades = perf.get('total_trades', 0)
        total_pnl = perf.get('pnl', 0)
        avg_pnl = (total_pnl / total_trades) if total_trades > 0 else 0
        rr = champ.get('metadata', {}).get('risk_reward', 'TBD')
        champ_stats = (
            f"🏆 **Champion (XAU_USD): {champ['version']}**\n"
            f"Avg PnL: ${avg_pnl:.2f}\n"
            f"Win Rate: {win_rate}\n"
            f"RR Ratio: {rr}"
        )
    if "status" in stats:
        return f"📊 **Daily Report**\n\n{stats['status']}\n\n{champ_stats}"
    msg = (
        f"📊 **Daily Performance Report**\n"
        f"Date: {stats.get('date', 'N/A')}\n"
        f"----------------------------\n"
        f"Total PnL: ${stats.get('total_pnl', 0):.2f}\n"
        f"Win Rate: {stats.get('win_rate', '0%')}\n"
        f"Trades Closed: {stats.get('trade_count', 0)}\n"
        f"----------------------------\n\n"
        f"{champ_stats}"
    )
    return msg

def cmd_status(text, context, exchange, runtime, compliance, tracker, breaker, notifier):
    """Read-only bot health dashboard."""
    if runtime:
        logger.info(f"[IDENTITY-AUDIT] cmd_status | ID: {id(runtime)} | Cycles: {runtime.cycle_count}")

    uptime = runtime.get_uptime_str()
    cycles = runtime.cycle_count
    last_cycle = runtime.last_cycle_timestamp
    last_cycle_str = last_cycle.strftime('%H:%M:%S UTC') if last_cycle else "N/A"

    conn_status = getattr(exchange, 'connection_status', 'UNKNOWN')
    env = settings.get('oanda_env', 'unknown')
    sim_mode = settings.get('simulation_mode', False)
    telegram_status = notifier.state

    summary = exchange.get_account_summary()
    equity = summary.get('equity') if summary else None
    pnl = 0.0
    if summary and tracker.load_equity_snapshot():
        pnl = equity - tracker.load_equity_snapshot()

    # Format equity display based on availability
    if equity is not None:
        equity_display = f"${equity:.2f}" + (" (Stale)" if not runtime.is_account_available else "")
    else:
        equity_display = "N/A"

    # Corrected: Use runtime state for account availability
    # Also wrap in try-except for safety if it calls other methods
    try:
        availability = "Available" if runtime.is_account_available is True else \
                       "Unavailable" if runtime.is_account_available is False else "Unknown"
        comp_status = compliance.get_status_summary(equity if runtime.is_account_available else None, pnl)
    except Exception as e:
        logger.error(f"Error calculating compliance status in cmd_status: {e}")
        availability = "Error"
        comp_status = "Status unavailable"

    open_trades = tracker.get_open_trades()
    trade_count = len(open_trades)

    breaker_status = "TRIPPED 🚨" if breaker.is_tripped() else "OK ✅"
    breaker_reason = breaker.last_reason if breaker.is_tripped() else "N/A"

    from core.state_manager import StateManager
    sm = StateManager()
    boot_count = sm.get_boot_count()
    errors = list(runtime.error_buffer)
    error_msg = "\n".join(errors) if errors else "None"

    report = (
        f"🤖 **Bot Health Status**\n"
        f"----------------------------\n"
        f"Status: RUNNING ✅\n"
        f"Uptime: {uptime}\n"
        f"Cycles: {cycles} (Last: {last_cycle_str})\n"
        f"Bot Starts: {boot_count}\n"
        f"----------------------------\n"
        f"OANDA: {conn_status} ({env})\n"
        f"Telegram: {telegram_status}\n"
        f"Simulation: {'Yes' if sim_mode else 'No'}\n"
        f"Account: {availability}\n"
        f"Equity: {equity_display}\n"
        f"Compliance: {comp_status}\n"
        f"----------------------------\n"
        f"Open Trades: {trade_count}\n"
        f"Circuit Breaker: {breaker_status}\n"
        f"CB Reason: {breaker_reason}\n"
        f"----------------------------\n"
        f"Recent Errors:\n{error_msg}"
    )
    return report

from core.lock_manager import acquire_lock, release_lock

# --- Global Configuration ---
MONITORED_ASSETS = [
    {"symbol": "XAU_USD", "gran": "H1"},
    {"symbol": "BTC_USD", "gran": "H1"},
    {"symbol": "NAS100_USD", "gran": "H1"},
]
POLL_INTERVAL = 30
MAX_OPEN_POSITIONS = 1
FREEZE_POST_MORTEM = True

class LiveBotOrchestrator:
    """
    Authoritative coordinator for bot lifecycle, outage state, and recovery.
    """
    def __init__(self, runtime_state: BotRuntimeState, state_manager: StateManager, notifier: NotificationManager, exchange: ExchangeConnector):
        self.runtime_state = runtime_state
        self.state_manager = state_manager
        self.notifier = notifier
        self.exchange = exchange
        self._outage_lock = threading.Lock()

    def _enter_outage(self, source: str, error: Exception):
        """
        Thread-safe, idempotent transition into an outage state.
        """
        start_wait = time.perf_counter()
        logger.info(f"[LOCK_TRACE] _enter_outage | Thread: {threading.get_ident()} | Action: Attempting lock")
        with self._outage_lock:
            wait_duration = (time.perf_counter() - start_wait) * 1000
            logger.info(f"[LOCK_TRACE] _enter_outage | Thread: {threading.get_ident()} | Action: Lock acquired | Wait: {wait_duration:.2f}ms")

            start_hold = time.perf_counter()
            now_utc = datetime.now(timezone.utc)

            # Idempotency: Check if we are already in this outage generation
            if self.runtime_state.outage_generation_id == self.runtime_state.recovery_notified_generation_id:
                logger.info(f"Entering NEW outage. Source: {source} | Error: {error}")
                self.runtime_state.outage_generation_id += 1
                self.runtime_state.is_outage_active = True
                self.runtime_state.heartbeat_pending = True
            else:
                logger.debug(f"Already in outage {self.runtime_state.outage_generation_id}. Source {source} reporting failure: {error}")

            # Update component health
            if source == "telegram":
                self.runtime_state.connectivity_health["telegram"] = False
            elif source == "broker" or source == "network":
                self.runtime_state.connectivity_health["broker"] = False
                self.exchange.connection_status = "DISCONNECTED"

            # Atomic Persistence
            self.state_manager.save_heartbeat_metrics(
                self.runtime_state.last_heartbeat_time,
                self.runtime_state.heartbeat_due_at,
                self.runtime_state.heartbeat_pending,
                self.runtime_state.heartbeat_retry_count,
                self.runtime_state.next_retry_at,
                runtime_state=self.runtime_state
            )
            logger.info(f"Outage state persisted. Gen: {self.runtime_state.outage_generation_id} | Health: {self.runtime_state.connectivity_health}")

            hold_duration = (time.perf_counter() - start_hold) * 1000
            logger.info(f"[LOCK_TRACE] _enter_outage | Thread: {threading.get_ident()} | Action: Lock releasing | Duration: {hold_duration:.2f}ms")
        logger.info(f"[LOCK_TRACE] _enter_outage | Thread: {threading.get_ident()} | Action: Lock released")

    def verify_connectivity(self) -> bool:
        """
        Strict validation of all critical dependencies before closing an outage.
        """
        # 1. Telegram Health
        if self.notifier.state != "RUNNING":
            return False

        # 2. Broker Health (read-only probe)
        try:
            summary = self.exchange.get_account_summary(bypass_guard=True)
            if summary is None:
                return False
        except Exception:
            return False

        return True

    def handle_recovery(self, now_utc: datetime):
        """
        Handles the confirmed recovery sequence.
        """
        # Trigger recovery if: outage active AND health verified AND not currently sending
        if (self.runtime_state.is_outage_active and
            self.verify_connectivity() and
            not self.runtime_state.heartbeat_in_flight):

            # --- IMMEDIATE STATE REFRESH ---
            # We mark the connection as healthy BEFORE dispatching the notification
            # so that /status is consistent the moment the user is notified.
            self.exchange.connection_status = "CONNECTED"
            self.runtime_state.connectivity_health = {"telegram": True, "broker": True}
            # --------------------------------

            start_wait = time.perf_counter()
            logger.info(f"[LOCK_TRACE] handle_recovery | Thread: {threading.get_ident()} | Action: Attempting lock")
            with self._outage_lock:
                wait_duration = (time.perf_counter() - start_wait) * 1000
                logger.info(f"[LOCK_TRACE] handle_recovery | Thread: {threading.get_ident()} | Action: Lock acquired | Wait: {wait_duration:.2f}ms")

                start_hold = time.perf_counter()
                if self.runtime_state.outage_generation_id == self.runtime_state.recovery_notified_generation_id:
                    # Already notified for this generation
                    self.runtime_state.is_outage_active = False
                    hold_duration = (time.perf_counter() - start_hold) * 1000
                    logger.info(f"[LOCK_TRACE] handle_recovery | Thread: {threading.get_ident()} | Action: Lock releasing | Duration: {hold_duration:.2f}ms")
                    logger.info(f"[LOCK_TRACE] handle_recovery | Thread: {threading.get_ident()} | Action: Lock released")
                    return

                logger.info(f"Connectivity validated. Dispatching recovery for gen {self.runtime_state.outage_generation_id}...")

                # Recovery Message
                offline_duration = "unknown"
                if self.runtime_state.last_heartbeat_time:
                    diff = now_utc - self.runtime_state.last_heartbeat_time
                    offline_duration = f"{diff.total_seconds()/3600:.1f}h"

                recovery_msg = (
                    f"♻️ **Connectivity Restored**\n"
                    f"Offline duration: ~{offline_duration}\n"
                    f"Cycles caught up: {self.runtime_state.cycle_count}\n"
                    f"Bot state: RUNNING ✅"
                )

                # At-least-once delivery attempt
                future = self.notifier.send_sync(recovery_msg)
                if future:
                    self.runtime_state.current_heartbeat_future = future
                    self.runtime_state.heartbeat_in_flight = True
                    self.runtime_state.heartbeat_send_deadline = now_utc + timedelta(seconds=30)
                    logger.info("Recovery notification dispatched. Awaiting confirmation.")
                else:
                    logger.warning("Recovery message failed to schedule. Will retry next cycle.")

                hold_duration = (time.perf_counter() - start_hold) * 1000
                logger.info(f"[LOCK_TRACE] handle_recovery | Thread: {threading.get_ident()} | Action: Lock releasing | Duration: {hold_duration:.2f}ms")
            logger.info(f"[LOCK_TRACE] handle_recovery | Thread: {threading.get_ident()} | Action: Lock released")

    def finalize_recovery(self, now_utc: datetime):
        """
        Closes the outage state only after confirmed delivery of recovery notification.
        """
        if self.runtime_state.heartbeat_in_flight and self.runtime_state.current_heartbeat_future:
            future = self.runtime_state.current_heartbeat_future
            if future.done():
                try:
                    # Verify the actual result of the Future
                    result = future.result()
                    if result is None:
                        logger.warning("Recovery notification Future completed but returned None. Recovery not finalized.")
                        return

                    # Confirmed delivery
                    start_wait = time.perf_counter()
                    logger.info(f"[LOCK_TRACE] finalize_recovery | Thread: {threading.get_ident()} | Action: Attempting lock")
                    with self._outage_lock:
                        wait_duration = (time.perf_counter() - start_wait) * 1000
                        logger.info(f"[LOCK_TRACE] finalize_recovery | Thread: {threading.get_ident()} | Action: Lock acquired | Wait: {wait_duration:.2f}ms")

                        start_hold = time.perf_counter()
                        logger.info(f"Recovery confirmed for outage gen {self.runtime_state.outage_generation_id}")
                        self.runtime_state.recovery_notified_generation_id = self.runtime_state.outage_generation_id
                        self.runtime_state.is_outage_active = False
                        self.runtime_state.heartbeat_pending = False
                        self.runtime_state.connectivity_health = {"telegram": True, "broker": True}

                        self.state_manager.save_heartbeat_metrics(
                            self.runtime_state.last_heartbeat_time,
                            self.runtime_state.heartbeat_due_at,
                            self.runtime_state.heartbeat_pending,
                            self.runtime_state.heartbeat_retry_count,
                            self.runtime_state.next_retry_at,
                            runtime_state=self.runtime_state
                        )

                        # ATOMIC CLEANUP: Prevent redundant finalizations
                        self.runtime_state.current_heartbeat_future = None
                        self.runtime_state.heartbeat_in_flight = False

                        hold_duration = (time.perf_counter() - start_hold) * 1000
                        logger.info(f"[LOCK_TRACE] finalize_recovery | Thread: {threading.get_ident()} | Action: Lock releasing | Duration: {hold_duration:.2f}ms")
                    logger.info(f"[LOCK_TRACE] finalize_recovery | Thread: {threading.get_ident()} | Action: Lock released")
                except Exception as e:
                    logger.warning(f"Recovery confirmation error (Future result failed): {e}")
                    # Leave is_outage_active=True and let retry logic handle it

def main():
    # --- Single Instance Lock ---
    is_managed = os.getenv("BOT_MANAGED_BY_LAUNCHER", "false").lower() == "true"

    lock_file = "bot.lock"
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                content = f.read().strip()

            if content:
                parts = content.split('|')
                if len(parts) >= 5:
                    launcher_pid = int(parts[0])
                    session_uuid = parts[4]

                    import psutil
                    if psutil.pid_exists(launcher_pid):
                        try:
                            proc = psutil.Process(launcher_pid)
                            cmdline = " ".join(proc.cmdline())
                            if "run_bot.ps1" in cmdline:
                                if not is_managed:
                                    logger.error(f"Managed bot instance already running (Launcher PID: {launcher_pid}). Manual launch refused.")
                                    return
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
        except (ValueError, OSError) as e:
            logger.debug(f"Could not parse launcher lock: {e}")

    if not is_managed:
        direct_lock = "live_main.lock"
        success, pid = acquire_lock(direct_lock)
        if not success:
            logger.error(f"Another manual instance of the bot is running (PID: {pid}). Exiting.")
            return
    else:
        logger.info("Bot startup: Managed by launcher (skipping local lock acquisition).")

    try:
        api_key = settings['api_key']
        account_id = settings['account_id']

        if not api_key or not account_id:
            logger.error("Missing OANDA_API_KEY or OANDA_ACCOUNT_ID in environment variables.")
            return

        logger.info("Initializing Autonomous Live Bot...")

        runtime_state = BotRuntimeState()
        state_manager = StateManager()

        boot_count = state_manager.get_boot_count() + 1
        state_manager.save_boot_count(boot_count)
        runtime_state.boot_count = boot_count
        logger.info(f"Bot Startup: Boot Count = {boot_count}")

        # Recover heartbeat and outage state
        metrics = state_manager.load_heartbeat_metrics()
        runtime_state.last_heartbeat_time = metrics[0]
        runtime_state.heartbeat_due_at = metrics[1]
        runtime_state.heartbeat_pending = metrics[2]
        runtime_state.heartbeat_retry_count = metrics[3]
        runtime_state.next_retry_at = metrics[4]
        runtime_state.outage_generation_id = metrics[5]
        runtime_state.recovery_notified_generation_id = metrics[6]
        runtime_state.connectivity_health = metrics[7]
        runtime_state.is_outage_active = metrics[8]

        data_dir = settings['data_dir']
        data_dir.mkdir(parents=True, exist_ok=True)

        dl = DataLake(api_key=api_key, account_id=account_id)
        engine = StrategyEngine()
        reviewer = AIReviewer()
        risk_manager = RiskManager(risk_per_trade=0.01)
        tracker = TradeTracker()
        evolver = PostMortemAgent()
        news_guard = NewsGuard()
        signal_tracker = SignalTracker()
        circuit_breaker = CircuitBreaker(threshold=5)

        saved_equity = tracker.load_equity_snapshot()
        if saved_equity:
            logger.info(f"Recovered daily equity benchmark from disk: ${saved_equity:.2f}")

        backtester = ParallelBacktester(dl)
        strategist = StrategistAgent(backtester=backtester)
        registry = StrategyRegistry()

        notifier = NotificationManager(
            token=os.getenv("TELEGRAM_API_KEY"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            runtime_state=runtime_state
        )

        is_live_enabled = os.getenv("LIVE_TRADING", "False").lower() == "true"
        simulation_mode = not is_live_enabled

        id_prefix = account_id.split('-')[0]
        if (is_live_enabled and id_prefix == "101") or (not is_live_enabled and id_prefix == "001"):
            error_msg = f"CRITICAL: Account ID prefix ({id_prefix}) mismatches LIVE_TRADING setting ({is_live_enabled}). Aborting for safety."
            logger.critical(error_msg)
            notifier.send_sync(error_msg)
            return

        exchange = ExchangeConnector(
            api_key=api_key,
            account_id=account_id,
            simulation_mode=simulation_mode
        )

        portfolio_manager = PortfolioManager()
        compliance_guard = ComplianceGuard(
            max_intraday_drawdown=150.0,
            daily_loss_limit=500.0,
            max_consecutive_losses=3
        )
        session_filter = SessionFilter()
        candle_guard = CandleGuard()

        # Setup Orchestrator
        orchestrator = LiveBotOrchestrator(runtime_state, state_manager, notifier, exchange)

        notifier.register_callback('positions', lambda t, c: cmd_positions(t, c, exchange))
        notifier.register_callback('close_all', lambda t, c: cmd_close_all(t, c, exchange))
        notifier.register_callback('close_partial', lambda t, c: cmd_close_partial(t, c, exchange))
        notifier.register_callback('move_be', cmd_move_be)
        notifier.register_callback('daily', lambda t, c: cmd_daily(t, c, tracker, registry))
        notifier.register_callback('status', lambda t, c: cmd_status(t, c, exchange, runtime_state, compliance_guard, tracker, circuit_breaker, notifier))
        notifier.register_callback('message', portfolio_manager.handle_response)

        logger.info("Performing State Recovery/Reconciliation...")
        broker_positions = exchange.get_open_positions()
        synced, mismatch_msg = state_manager.reconcile_with_broker(broker_positions)

        if not synced:
            alert_msg = f"⚠️ STARTUP MISMATCH: Broker and State are out of sync!\nDetails: {mismatch_msg}\n\nAction: Bot will continue, but please review active trades."
            logger.warning(alert_msg)
            notifier.send_sync(alert_msg)
        else:
            logger.info("Reconciliation complete. State is synchronized with broker.")

        notifier.start_listener(orchestrator=orchestrator)

    except Exception as e:
        logger.exception(f"Critical error during bot initialization: {e}")
        return

    logger.info(f"Bot is now LIVE. Monitoring {len(MONITORED_ASSETS)} assets every {POLL_INTERVAL}s.")

    try:
        while True:
            now_utc = datetime.now(timezone.utc)

            # --- OANDA Auth Recovery ---
            if exchange.connection_status == "AUTH_FAILED":
                logger.warning("Broker auth failed. Triggering recovery flow...")
                exchange.handle_auth_recovery(state_manager)

            # 1. Broker Connectivity Check (Trigger Outage if failed)
            summary = exchange.get_account_summary()
            if summary is None:
                logger.warning("Account summary unavailable. Checking for outage...")
                orchestrator._enter_outage("broker", Exception("Account summary returned None"))
                runtime_state.is_account_available = False
                equity = None
                balance = None
            else:
                equity = summary['equity']
                balance = summary['balance']
                runtime_state.is_account_available = True

            if runtime_state.is_account_available:
                compliance_guard.update_daily_start(equity)
                tracker.save_equity_snapshot(equity)

            start_equity = tracker.load_equity_snapshot()
            if start_equity is None:
                start_equity = equity if runtime_state.is_account_available else 0.0

            current_pnl = (equity - start_equity) if runtime_state.is_account_available else 0.0
            is_compliant, reason = compliance_guard.check_compliance(equity if runtime_state.is_account_available else None, current_pnl)

            if not is_compliant:
                error_msg = f"🚨 COMPLIANCE VIOLATION: {reason}\n\nExecuting Emergency Shutdown..."
                notifier.send_sync(error_msg)
                logger.critical(error_msg)
                all_pos = exchange.get_open_positions()
                for p in all_pos:
                    inst = p.get('instrument', 'XAU_USD')
                    units = float(p.get('long', {}).get('units', 0)) - float(p.get('short', {}).get('units', 0))
                    if units != 0:
                        exchange.place_market_order(inst, -units)
                return

            # --- Heartbeat and Recovery Logic ---
            heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", 14400))

            # A. Finalize previous recovery/heartbeat attempt
            orchestrator.finalize_recovery(now_utc)

            # B. Process in-flight heartbeat result
            if runtime_state.heartbeat_in_flight and runtime_state.current_heartbeat_future:
                future = runtime_state.current_heartbeat_future
                if future.done():
                    try:
                        logger.info("Heartbeat delivery confirmed.")
                        runtime_state.last_heartbeat_time = now_utc
                        runtime_state.heartbeat_due_at = now_utc + timedelta(seconds=heartbeat_interval)

                        if runtime_state.heartbeat_pending:
                            runtime_state.recovery_notified_generation_id = runtime_state.outage_generation_id
                            logger.info(f"Recovery confirmed for outage gen {runtime_state.outage_generation_id}")

                        runtime_state.heartbeat_pending = False
                        runtime_state.heartbeat_in_flight = False
                        runtime_state.heartbeat_retry_count = 0
                        runtime_state.next_retry_at = None
                        runtime_state.current_heartbeat_future = None

                        state_manager.save_heartbeat_metrics(
                            runtime_state.last_heartbeat_time,
                            runtime_state.heartbeat_due_at,
                            runtime_state.heartbeat_pending,
                            runtime_state.heartbeat_retry_count,
                            runtime_state.next_retry_at,
                            runtime_state=runtime_state
                        )
                    except Exception as e:
                        logger.warning(f"Heartbeat delivery failed: {e}")
                        runtime_state.heartbeat_in_flight = False
                        runtime_state.heartbeat_pending = True
                        runtime_state.current_heartbeat_future = None
                        runtime_state.heartbeat_retry_count += 1
                        backoff = [30, 60, 120, 300][min(runtime_state.heartbeat_retry_count-1, 3)]
                        runtime_state.next_retry_at = now_utc + timedelta(seconds=backoff)
                        state_manager.save_heartbeat_metrics(
                            runtime_state.last_heartbeat_time,
                            runtime_state.heartbeat_due_at,
                            runtime_state.heartbeat_pending,
                            runtime_state.heartbeat_retry_count,
                            runtime_state.next_retry_at,
                            runtime_state=runtime_state
                        )

            # C. Check for recovery notification trigger
            orchestrator.handle_recovery(now_utc)

            # D. Trigger heartbeat if due
            if (runtime_state.last_heartbeat_time is None or
                (runtime_state.heartbeat_due_at and now_utc >= runtime_state.heartbeat_due_at) or
                (runtime_state.next_retry_at and now_utc >= runtime_state.next_retry_at) or
                (not runtime_state.heartbeat_due_at and not runtime_state.next_retry_at and
                 (now_utc - runtime_state.last_heartbeat_time).total_seconds() >= heartbeat_interval if runtime_state.last_heartbeat_time else True)):

                if runtime_state.heartbeat_in_flight:
                    if runtime_state.heartbeat_send_deadline and now_utc > runtime_state.heartbeat_send_deadline:
                        logger.warning("Heartbeat send deadline exceeded. Marking as failed.")
                        runtime_state.heartbeat_in_flight = False
                        runtime_state.heartbeat_pending = True
                        runtime_state.current_heartbeat_future = None
                    else:
                        continue

                runtime_state.heartbeat_in_flight = True
                runtime_state.heartbeat_attempt_id += 1
                current_attempt_id = runtime_state.heartbeat_attempt_id

                try:
                    heartbeat_msg = (
                        f"💓 **Bot Heartbeat**\n"
                        f"Uptime: {runtime_state.get_uptime_str()}\n"
                        f"Cycles: {runtime_state.cycle_count}\n"
                        f"Compliance: {compliance_guard.get_status_summary(equity if runtime_state.is_account_available else None, current_pnl)}\n"
                        f"Trades: {len(tracker.get_open_trades())} open\n"
                        f"Env: {settings.get('oanda_env', 'unknown')} | Sim: {settings.get('simulation_mode', False)}"
                    )

                    if notifier.state == "RUNNING":
                        future = notifier.send_sync(heartbeat_msg)
                        if future:
                            runtime_state.current_heartbeat_future = future
                            runtime_state.heartbeat_send_deadline = now_utc + timedelta(seconds=30)
                            logger.info(f"Heartbeat {current_attempt_id} dispatched.")
                        else:
                            raise Exception("Failed to schedule Future")
                    else:
                        logger.warning(f"Heartbeat skipped: Notifier is {notifier.state}.")
                        orchestrator._enter_outage("telegram", Exception(f"Notifier state {notifier.state}"))
                        runtime_state.heartbeat_in_flight = False
                        runtime_state.heartbeat_retry_count += 1
                        backoff = [30, 60, 120, 300][min(runtime_state.heartbeat_retry_count-1, 3)]
                        runtime_state.next_retry_at = now_utc + timedelta(seconds=backoff)
                except Exception as e:
                    logger.error(f"Heartbeat dispatch error: {e}")
                    orchestrator._enter_outage("telegram", e)
                    runtime_state.heartbeat_in_flight = False
                    runtime_state.heartbeat_retry_count += 1
                    backoff = [30, 60, 120, 300][min(runtime_state.heartbeat_retry_count-1, 3)]
                    runtime_state.next_retry_at = now_utc + timedelta(seconds=backoff)

            for asset in MONITORED_ASSETS:
                run_live_cycle(
                    asset['symbol'],
                    asset['gran'],
                    exchange,
                    engine,
                    reviewer,
                    risk_manager,
                    dl,
                    notifier,
                    tracker,
                    registry,
                    session_filter,
                    candle_guard,
                    news_guard,
                    signal_tracker,
                    circuit_breaker,
                    orchestrator
                )

            open_trades = tracker.get_open_trades()
            if open_trades:
                for asset in MONITORED_ASSETS:
                    manage_active_trades(exchange, tracker, notifier, asset['symbol'])

            evolver.run_evolutionary_cycle() if not FREEZE_POST_MORTEM else logger.debug("PostMortemAgent frozen by configuration.")

            if datetime.now().hour == 0 and datetime.now().minute == 0:
                logger.info("Strategist: Scheduled daily strategy generation...")
                for asset in MONITORED_ASSETS:
                    new_strat = strategist.generate_new_strategy(asset['symbol'], asset['gran'])
                    if new_strat:
                        registry.add_challenger(new_strat)

            challengers = [s for s in registry.get_all_strategies("XAU_USD") if not s.get("is_champion")]
            if challengers:
                worst_challenger = min(challengers, key=lambda x: x["performance"].get("win_rate", 0))
                if worst_challenger["performance"].get("total_trades", 0) >= 5:
                    logger.info(f"Strategist: Optimizing underperforming strategy {worst_challenger['version']}...")
                    optimized_strat = strategist.optimize_strategy(worst_challenger, worst_challenger['performance'])
                    if optimized_strat:
                        registry.add_challenger(optimized_strat)

            for asset in MONITORED_ASSETS:
                promoted_version = registry.check_for_promotion(asset['symbol'])
                if promoted_version:
                    logger.info(f"🚀 STRATEGY PROMOTED for {asset['symbol']}: {promoted_version} is now the Champion!")
                    notifier.send_sync(f"🚀 STRATEGY PROMOTED for {asset['symbol']}: {promoted_version} is now the Champion!")

            portfolio_manager.check_health(exchange, notifier)

            if datetime.now().hour == 0 and datetime.now().minute == 0:
                logger.info("Scheduling daily performance summary report...")
                day_start = (now_utc - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                daily_stats = risk_manager.calculate_account_daily_pnl(exchange, day_start)
                report_msg = (
                    f"📊 **Daily Verified Report**\n"
                    f"Date: {now_utc.strftime('%Y-%m-%d')}\n"
                    f"----------------------------\n"
                    f"Total PnL: ${daily_stats['total_pnl']:.2f}\n"
                    f"Verified Fills: {daily_stats['verified_trades']}\n"
                    f"Rejected/Cancelled: {daily_stats['rejected_orders']}\n"
                    f"----------------------------"
                )
                notifier.send_sync(report_msg)

            for asset in MONITORED_ASSETS:
                manage_active_trades(exchange, tracker, notifier, asset['symbol'])

            logger.info(f"Cycle complete. Sleeping for {POLL_INTERVAL}s.")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        release_lock("bot.lock")
        try:
            notifier.stop_listener()
        except Exception as e:
            logger.error(f"Error stopping Telegram listener: {e}")

if __name__ == "__main__":
    main()
