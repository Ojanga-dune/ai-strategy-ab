# AI Strategy Lab - Orchestration Loop
# This is the main entry point for the Generate -> Backtest -> Evolve loop.

import sys
import logging
from core.datalake import DataLake
from core.strategy_engine import StrategyEngine
from core.ai_reviewer import AIReviewer
from core.analytics import Analytics
from architect.generator import StrategyGenerator
from architect.optimizer import StrategyOptimizer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("Initializing AI Strategy Lab...")

    # 1. Initialize Core Components
    dl = DataLake(base_path="C:\\Users\\Admin\\ai-strategy-lab\\data\\lake")
    engine = StrategyEngine()
    reviewer = AIReviewer()
    analytics = Analytics()
    generator = StrategyGenerator()
    optimizer = StrategyOptimizer()

    # 2. The Evolutionary Loop
    # In a real run, this would iterate multiple times
    try:
        # Generate a strategy ruleset
        strategy = generator.generate_initial_strategy()
        logger.info(f"Generated Strategy: {strategy['version']}")

        # Step 1: Deterministic Pass (The Sieve)
        candidates = engine.find_candidates(strategy, dl)
        logger.info(f"Found {len(candidates)} candidate signals.")

        # Step 2: AI Review Pass (The Brain)
        verified_trades = reviewer.validate_signals(candidates, dl)
        logger.info(f"AI verified {len(verified_trades)} high-probability trades.")

        # Step 3: Quantitative Analytics
        metrics = analytics.calculate_performance(verified_trades)
        logger.info(f"Performance Metrics: {metrics}")

        # Step 4: Evolution/Optimization
        next_strategy = optimizer.evolve(strategy, metrics, verified_trades)
        logger.info(f"Evolved to version: {next_strategy['version']}")

    except Exception as e:
        logger.error(f"Error in orchestration loop: {e}", exc_info=True)

if __name__ == "__main__":
    main()
