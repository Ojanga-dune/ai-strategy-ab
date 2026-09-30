import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor
from core.datalake import DataLake
from core.strategy_engine import StrategyEngine
from core.analytics import Analytics

logger = logging.getLogger(__name__)

@dataclass
class TradeOutcome:
    """Represents the result of a simulated trade."""
    status: str  # 'CLOSED'
    pnl: float
    exit_timestamp: datetime
    reason: str  # 'TP' or 'SL'
    win: bool

class OutcomeEngine:
    """
    Handles the micro-simulation of individual trades.
    Determines if SL or TP was hit first by scanning historical candles.
    """
    def simulate_trade(self, trade_dna: Dict[str, Any], historical_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Determines the outcome of a single trade by scanning subsequent candles.

        Args:
            trade_dna: Contains 'entry_price', 'sl', 'tp', 'timestamp', and 'strategy_version'.
            historical_df: The historical candle data with time index.

        Returns:
            Dict containing trade outcome details.
        """
        entry_price = trade_dna['entry_price']
        sl = trade_dna['sl']
        tp = trade_dna['tp']
        timestamp = pd.to_datetime(trade_dna['timestamp'])

        # Determine direction (Long if TP > Entry)
        is_long = tp > entry_price

        # Slice historical data to start AFTER the entry timestamp
        future_candles = historical_df.loc[timestamp:].iloc[1:]

        if future_candles.empty:
            return {
                'status': 'OPEN',
                'pnl': 0.0,
                'exit_timestamp': None,
                'reason': 'No future data',
                'win': False
            }

        for time, candle in future_candles.iterrows():
            high = candle['high']
            low = candle['low']

            if is_long:
                # Check SL first (Conservative approach)
                if low <= sl:
                    pnl = sl - entry_price
                    return {
                        'status': 'CLOSED',
                        'pnl': float(pnl),
                        'exit_timestamp': time,
                        'reason': 'SL',
                        'win': False
                    }
                # Check TP
                if high >= tp:
                    pnl = tp - entry_price
                    return {
                        'status': 'CLOSED',
                        'pnl': float(pnl),
                        'exit_timestamp': time,
                        'reason': 'TP',
                        'win': True
                    }
            else: # Short
                # Check SL first
                if high >= sl:
                    pnl = entry_price - sl
                    return {
                        'status': 'CLOSED',
                        'pnl': float(pnl),
                        'exit_timestamp': time,
                        'reason': 'SL',
                        'win': False
                    }
                # Check TP
                if low <= tp:
                    pnl = entry_price - tp
                    return {
                        'status': 'CLOSED',
                        'pnl': float(pnl),
                        'exit_timestamp': time,
                        'reason': 'TP',
                        'win': True
                    }

        # If the loop ends without hitting SL or TP
        return {
            'status': 'OPEN',
            'pnl': 0.0,
            'exit_timestamp': None,
            'reason': 'Data ended',
            'win': False
        }

class ParallelBacktester:
    """
    Orchestrates a full historical simulation for a given strategy.
    """
    def __init__(self, datalake: DataLake):
        self.datalake = datalake
        self.outcome_engine = OutcomeEngine()
        self.analytics = Analytics()
        self.strategy_engine = StrategyEngine()

    def run_backtest(self, strategy_config: Dict[str, Any], instrument: str, granularity: str, days: int = 1825) -> Dict[str, Any]:
        """
        Executes a full backtest over a specified historical window.
        Defaults to 1825 days (~5 years).
        """
        logger.info(f"Running deep historical backtest (5Y) for {strategy_config['version']} on {instrument} {granularity}...")

        # 1. Load historical data
        df = self.datalake.load_data(instrument, granularity)
        if df.empty:
            return {"status": "Error", "message": "No historical data available."}

        # Slice to the desired window
        cutoff_date = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=days)
        df = df[df.index >= cutoff_date]

        # 2. Generate signals using the existing StrategyEngine
        # We use a mock datalake that simply returns the pre-sliced df
        class BacktestDataMock:
            def __init__(self, df): self.df = df
            def load_data(self, inst, gran): return self.df

        candidates = self.strategy_engine.find_candidates(strategy_config, BacktestDataMock(df))

        if not candidates:
            return {"status": "No trades", "total_trades": 0}

        logger.info(f"Backtest: Generated {len(candidates)} signals over 5 years. Simulating outcomes...")

        # 3. Parallel Simulation of outcomes
        with ProcessPoolExecutor() as executor:
            # We wrap the call because ProcessPoolExecutor needs a top-level function or picklable object
            futures = [executor.submit(self.outcome_engine.simulate_trade, candle, df) for candle in candidates]
            outcomes = [f.result() for f in futures]

        # 4. Aggregate and Analyze
        closed_trades = [o for o in outcomes if o['status'] == 'CLOSED']

        if not closed_trades:
            return {"status": "No closed trades", "total_trades": len(candidates)}

        performance = self.analytics.calculate_performance(closed_trades)
        performance['total_simulated_trades'] = len(candidates)
        performance['closed_trades'] = len(closed_trades)
        performance['test_period_days'] = days

        return performance
