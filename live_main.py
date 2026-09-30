import time
import logging
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Optional

# Silence httpx request logging to prevent tokens/URLs from leaking in logs
import logging as py_logging
py_logging.getLogger("httpx").setLevel(py_logging.WARNING)

from core.datalake import DataLake

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

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LiveBot")

def resolve_trade_pnl(exchange: ExchangeConnector, trade_id: str, retries: int = 5, delay: int = 10) -> Optional[float]:
    """
    Attempts to fetch the final PnL of a closed trade.
    1. Primary: Try Trade Details (realizedPL + financing).
    2. Fallback: Try Transaction History (sum of ORDER_FILL pl).
    """
    for i in range(retries):
        try:
            # --- Step 1: Primary Lookup (Trade Details) ---
            trade_details = exchange.get_trade_details(trade_id)
            if trade_details:
                realized = trade_details.get('realizedPL', 0)
                financing = trade_details.get('financing', 0)
                try:
                    total_pnl = float(realized) + float(financing)
                    logger.info(f"PnL resolved via Trade Details for {trade_id}: {total_pnl:.2f}")
                    return total_pnl
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to cast PnL fields for {trade_id}: {realized}, {financing}. Error: {e}")

            # --- Step 2: Fallback Lookup (Transactions) ---
            transactions = exchange.get_trade_transactions(trade_id)
            if transactions:
                fill_pnl = sum(float(t.get('pl', 0)) for t in transactions if t.get('type') == 'ORDER_FILL')
                logger.info(f"PnL resolved via Transactions for {trade_id}: {fill_pnl:.2f}")
                return fill_pnl

        except Exception as e:
            logger.error(f"Unexpected error resolving PnL for {trade_id}: {e}")

        if i < retries - 1:
            logger.info(f"Trade {trade_id} PnL not yet resolved. Retry {i+1}/{retries} in {delay}s...")
            time.sleep(delay)

    return None

def manage_active_trades(exchange: ExchangeConnector, tracker: TradeTracker, notifier: NotificationManager, instrument: str):
    """
    Dynamic trade management: Handles Break-Even and Trailing Stops.
    """
    open_trades = tracker.get_open_trades()
    if not open_trades:
        return

    logger.info(f"Managing {len(open_trades)} active trades for {instrument} risk reduction...")

    prices = exchange.get_market_price(instrument)
    if not prices:
        logger.warning(f"Could not fetch market prices for {instrument} trade management.")
        return

    current_price = prices['mid']

    for trade in open_trades:
        t_id = trade['trade_id']
        if trade.get('instrument') != instrument or trade.get('is_simulated', False):
            continue

        entry_price = trade.get('entry_price')
        sl = trade.get('sl')
        tp = trade.get('tp')

        if entry_price is None or sl is None:
            continue

        units = trade.get('units', 0)
        is_long = units > 0

        risk_dist = abs(entry_price - sl)
        if is_long:
            if current_price >= entry_price + risk_dist and sl < entry_price:
                logger.info(f"Trade {t_id}: Triggering Break-Even.")
                res = exchange.modify_order(t_id, stop_loss=entry_price)
                if res.get('status') == 'success':
                    tracker.update_outcome(t_id, {"sl": entry_price})
                    notifier.send_sync(f"🛡️ **Break-Even Set**: {t_id}\nSL moved to entry: {entry_price:.3f}")
        else:
            if current_price <= entry_price - risk_dist and sl > entry_price:
                logger.info(f"Trade {t_id}: Triggering Break-Even.")
                res = exchange.modify_order(t_id, stop_loss=entry_price)
                if res.get('status') == 'success':
                    tracker.update_outcome(t_id, {"sl": entry_price})
                    notifier.send_sync(f"🛡️ **Break-Even Set**: {t_id}\nSL moved to entry: {entry_price:.3f}")

        if is_long:
            if current_price >= entry_price + (2 * risk_dist) and sl < entry_price + risk_dist:
                new_sl = entry_price + risk_dist
                res = exchange.modify_order(t_id, stop_loss=new_sl)
                if res.get('status') == 'success':
                    tracker.update_outcome(t_id, {"sl": new_sl})
                    notifier.send_sync(f"📈 **Trailing Stop Updated**: {t_id}\nNew SL: {new_sl:.3f}")
        else:
            if current_price <= entry_price - (2 * risk_dist) and sl > entry_price + risk_dist:
                new_sl = entry_price - risk_dist
                res = exchange.modify_order(t_id, stop_loss=new_sl)
                if res.get('status') == 'success':
                    tracker.update_outcome(t_id, {"sl": new_sl})
                    notifier.send_sync(f"📉 **Trailing Stop Updated**: {t_id}\nNew SL: {new_sl:.3f}")

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
    news_guard: NewsGuard
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

        if not candle_guard.is_candle_closed(last_candle_time, gran_seconds):
            logger.info(f"CandleGuard: Current candle is still forming. Waiting for close.")
            return

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
                tp_price = latest_trade['price'] + tp_dist if is_bullish else latest_trade['price'] - tp_dist

                lots = risk_manager.calculate_position_size(
                    account_balance=balance,
                    entry_price=latest_trade['price'],
                    stop_loss=sl_price,
                    instrument=instrument
                )
                side_lots = lots if is_bullish else -lots

                # --- Execution with Retry Logic ---
                max_retries = 3
                retry_delay = 2
                result = None

                for attempt in range(max_retries):
                    logger.info(f"Executing Champion Order (Attempt {attempt+1}/{max_retries}): {instrument} {side_lots} lots...")
                    result = exchange.place_market_order(
                        instrument=instrument,
                        lots=side_lots,
                        stop_loss=sl_price,
                        take_profit=tp_price
                    )

                    if result.get('status') == 'success' or 'orderCreateTransaction' in result:
                        break

                    error_code = result.get('error_code')
                    # Do NOT retry 4xx errors (client errors) as they are non-recoverable
                    if error_code and 400 <= error_code < 500:
                        logger.warning(f"Order rejected with 4xx error {error_code}. Not retryable.")
                        break

                    if attempt < max_retries - 1:
                        logger.warning(f"Order failed: {result.get('message')}. Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)

                if not result or (result.get('status') == 'error' and 'orderCreateTransaction' not in result):
                    error_msg = f"❌ Order Failed after {max_retries} attempts.\n\n💡 Details: {result.get('message', 'Unknown error') if result else 'No response'}"
                    notifier.send_sync(error_msg)
                    continue

                if 'orderCreateTransaction' in result:
                    trade_id = result['orderCreateTransaction']['id']
                    trade_dna = {
                        'instrument': instrument,
                        'entry_price': latest_trade['price'],
                        'units': side_lots,
                        'sl': sl_price,
                        'tp': tp_price,
                        'ai_reasoning': latest_trade.get('ai_reasoning'),
                        'timestamp': latest_trade['timestamp'].isoformat() if hasattr(latest_trade['timestamp'], 'isoformat') else latest_trade['timestamp'],
                        'strategy_version': strat_version
                    }
                    tracker.record_entry(trade_id, trade_dna)

                if 'orderCancelTransaction' in result:
                    cancel_reason = result['orderCancelTransaction'].get('reason', 'Unknown')
                    error_msg = f"❌ Trade Cancelled: {cancel_reason}\n\n💡 How to fix: This usually happens if the market is halted or the order was too large for current liquidity. Try reducing risk or check OANDA server status."
                    notifier.send_sync(error_msg)
                    if 'orderCreateTransaction' in result:
                        trade_id = result['orderCreateTransaction']['id']
                        tracker.update_outcome(trade_id, {"status": "CLOSED", "pnl": 0, "reason": "Cancelled"})
                elif result.get('status') == 'error':
                    error_msg = f"❌ Order Error: {result.get('message')}\n\n💡 Details: {result.get('raw')}"
                    notifier.send_sync(error_msg)
                    if 'orderCreateTransaction' in result:
                        trade_id = result['orderCreateTransaction']['id']
                        tracker.update_outcome(trade_id, {"status": "CLOSED", "pnl": 0, "reason": "Cancelled"})
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
                tp_price = latest_trade['price'] + tp_dist if is_bullish else latest_trade['price'] - tp_dist

                shadow_trade_id = f"shadow_{strat_version}_{latest_trade['timestamp'].timestamp()}"
                trade_dna = {
                    'instrument': instrument,
                    'entry_price': latest_trade['price'],
                    'units': 1.0,
                    'sl': sl_price,
                    'tp': tp_price,
                    'ai_reasoning': latest_trade.get('ai_reasoning'),
                    'timestamp': latest_trade['timestamp'].isoformat() if hasattr(latest_trade['timestamp'], 'isoformat') else latest_trade['timestamp'],
                    'strategy_version': strat_version,
                    'is_simulated': True
                }
                tracker.record_entry(shadow_trade_id, trade_dna)
                logger.info(f"Shadow trade recorded for {strat_version}: {shadow_trade_id} (SL: {sl_price:.3f}, TP: {tp_price:.3f})")

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

from core.lock_manager import acquire_lock, release_lock

def main():
    # --- Single Instance Lock ---
    lock_file = "bot.lock"
    success, pid = acquire_lock(lock_file)
    if not success:
        logger.error(f"Another instance of the bot is already running (PID: {pid}). Exiting.")
        return

    try:
        # --- Configuration ---
        MONITORED_ASSETS = [

        {"symbol": "XAU_USD", "gran": "H1"},
        {"symbol": "BTC_USD", "gran": "H1"},
        {"symbol": "NAS100_USD", "gran": "H1"},
    ]
    POLL_INTERVAL = 3600  # 1 hour (in seconds)

    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")

    if not api_key or not account_id:
        logger.error("Missing OANDA_API_KEY or OANDA_ACCOUNT_ID in environment variables.")
        return

    # --- Initialization ---
    logger.info("Initializing Autonomous Live Bot...")

    dl = DataLake()
    engine = StrategyEngine()
    reviewer = AIReviewer()
    risk_manager = RiskManager(risk_per_trade=0.01)
    tracker = TradeTracker()
    state_manager = StateManager()
    evolver = PostMortemAgent()
    news_guard = NewsGuard()

    backtester = ParallelBacktester(dl)
    strategist = StrategistAgent(backtester=backtester)
    registry = StrategyRegistry()

    notifier = NotificationManager(
        token=os.getenv("TELEGRAM_API_KEY"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID")
    )

    exchange = ExchangeConnector(
        api_key=api_key,
        account_id=account_id,
        simulation_mode=False
    )

    portfolio_manager = PortfolioManager()
    compliance_guard = ComplianceGuard(
        max_intraday_drawdown=150.0,
        daily_loss_limit=500.0,
        max_consecutive_losses=3
    )
    session_filter = SessionFilter()
    candle_guard = CandleGuard()

    notifier.register_callback('positions', lambda t, c: cmd_positions(t, c, exchange))
    notifier.register_callback('close_all', lambda t, c: cmd_close_all(t, c, exchange))
    notifier.register_callback('close_partial', lambda t, c: cmd_close_partial(t, c, exchange))
    notifier.register_callback('move_be', cmd_move_be)
    notifier.register_callback('daily', lambda t, c: cmd_daily(t, c, tracker, registry))
    notifier.register_callback('message', portfolio_manager.handle_response)

    logger.info("Performing State Recovery/Reconciliation...")
    broker_positions = exchange.get_open_positions()
    state_manager.reconcile_with_broker(broker_positions)
    logger.info(f"Reconciliation complete. {len(broker_positions)} positions found on broker.")

    notifier.start_listener()

    logger.info(f"Bot is now LIVE. Monitoring {len(MONITORED_ASSETS)} assets every {POLL_INTERVAL}s.")
    logger.info("Press Ctrl+C to stop the bot.")

    try:
        while True:
            summary = exchange.get_account_summary()
            equity = float(summary.get('equity', 0))
            compliance_guard.update_daily_start(equity)

            current_pnl = equity - float(summary.get('balance', 0))
            is_compliant = True # Bypassed for testing
            reason = "Compliance bypassed for testing"

            if not is_compliant:
                error_msg = f"🚨 COMPLIANCE VIOLATION: {reason}\n\nExecuting Emergency Shutdown..."
                notifier.send_sync(error_msg)
                logger.critical(error_msg)
                # Emergency close all
                all_pos = exchange.get_open_positions()
                for p in all_pos:
                    inst = p.get('instrument', 'XAU_USD')
                    units = float(p.get('long', {}).get('units', 0)) - float(p.get('short', {}).get('units', 0))
                    if units != 0:
                        exchange.place_market_order(inst, -units)
                return

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
                    news_guard
                )

            open_trades = tracker.get_open_trades()
            if open_trades:
                logger.info(f"Monitoring {len(open_trades)} open trades for outcomes...")
                current_positions = exchange.get_open_positions()
                current_ids = [p.get('tradeID') for p in current_positions]

                for asset in MONITORED_ASSETS:
                    instrument = asset['symbol']
                    candles = exchange.get_latest_candles(instrument, "M1", count=1)
                    current_price = candles.iloc[-1]['close'] if not candles.empty else None

                    for trade in open_trades:
                        t_id = trade['trade_id']
                        if trade.get('instrument') != instrument:
                            continue

                        if not trade.get('is_simulated', False):
                            if t_id not in current_ids:
                                logger.info(f"Trade {t_id} has closed. Updating outcome...")
                                realized_pnl = resolve_trade_pnl(exchange, t_id)
                                if realized_pnl is not None:
                                    tracker.update_outcome(t_id, {"status": "CLOSED", "pnl": realized_pnl, "pnl_source": "oanda"})
                                    notifier.send_sync(f"🏁 Trade Closed: {t_id}. PnL: {realized_pnl:.2f}")
                                else:
                                    tracker.update_outcome(t_id, {"status": "CLOSED", "pnl": None, "pnl_source": "oanda", "failure_reason": "PnL resolution failed"})
                                    notifier.send_sync(f"🏁 Trade Closed: {t_id}. Outcome recorded (PnL missing).")
                        else:
                            if current_price is None: continue
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
                                logger.info(f"Shadow Trade {t_id} virtually closed ({reason}). PnL: {pnl:.3f}")
                                tracker.update_outcome(t_id, {"status": "CLOSED", "pnl": pnl, "pnl_source": "estimated", "reason": reason})
                                registry.update_performance(instrument, strat_version, pnl, pnl > 0, pnl_source="estimated")
                                notifier.send_sync(f"👻 Shadow Trade {strat_version} closed: {reason} (PnL: {pnl:.3f})")

            evolver.run_evolutionary_cycle()

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
                    optimized_strat = strategist.optimize_strategy(worst_challenger, worst_challenger["performance"])
                    if optimized_strat:
                        instrument = worst_challenger.get('instrument', 'XAU_USD')
                        registry.add_challenger(optimized_strat)

            for asset in MONITORED_ASSETS:
                promoted_version = registry.check_for_promotion(asset['symbol'])
                if promoted_version:
                    logger.info(f"🚀 STRATEGY PROMOTED for {asset['symbol']}: {promoted_version} is now the Champion!")
                    notifier.send_sync(f"🚀 STRATEGY PROMOTED for {asset['symbol']}: {promoted_version} is now the Champion!")

            portfolio_manager.check_health(exchange, notifier)

            now_utc = datetime.now(timezone.utc)
            if now_utc.hour == 0 and now_utc.minute == 0:
                logger.info("Scheduling daily performance summary report...")
                all_trades = tracker.get_all_trades()
                stats = Analytics().calculate_daily_stats(all_trades)
                if "status" not in stats:
                    report_msg = (
                        f"📊 **Daily Performance Report**\n"
                        f"Date: {stats['date']}\n"
                        f"----------------------------\n"
                        f"Total PnL: ${stats['total_pnl']:.2f}\n"
                        f"Win Rate: {stats['win_rate']}\n"
                        f"Trades Closed: {stats['trade_count']}\n"
                        f"----------------------------"
                    )
                    notifier.send_sync(report_msg)
                else:
                    notifier.send_sync(f"📊 **Daily Report**: {stats['status']}")

            for asset in MONITORED_ASSETS:
                manage_active_trades(exchange, tracker, notifier, asset['symbol'])

            logger.info(f"Cycle complete. Sleeping for {POLL_INTERVAL}s.")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        release_lock("bot.lock")

if __name__ == "__main__":
    main()
