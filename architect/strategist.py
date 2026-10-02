import logging
import json
import random
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import anthropic
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class StrategistAgent:
    """
    The Strategy Architect.
    Generates new trading strategy JSONs based on market regimes, 'Lessons Learned',
    and quantitative backtest performance.
    """
    def __init__(self, lessons_file: str = "data/lessons_learned.txt", backtester: Any = None, runtime_state: Any = None):
        self.lessons_file = Path(lessons_file)
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.backtester = backtester
        self.runtime_state = runtime_state

    def _get_lessons(self) -> List[str]:
        if not self.lessons_file.exists():
            return []
        with open(self.lessons_file, "r") as f:
            return [line.strip() for line in f.readlines() if line.strip()]

    def _call_llm(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Helper to call LLM and parse JSON response. Implements circuit breaker for degraded state."""
        # 1. Circuit Breaker Check
        if self.runtime_state:
            if self.runtime_state.research_engine_status == "DEGRADED":
                last_fail = self.runtime_state.last_research_failure_time
                if last_fail:
                    # Cooldown: 1 hour
                    elapsed = (datetime.now(timezone.utc) - last_fail).total_seconds()
                    if elapsed < 3600:
                        logger.info(f"Strategist: Research Engine is DEGRADED. Skipping API call (cooldown: {int(3600 - elapsed)}s remaining).")
                        return None

        try:
            message = self.client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            content = message.content[0].text

            # Extract JSON block if the LLM adds conversational filler
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return json.loads(content)
        except Exception as e:
            logger.error(f"Strategist LLM Error: {e}")
            # 2. Trigger Degraded State
            if self.runtime_state:
                self.runtime_state.research_engine_status = "DEGRADED"
                self.runtime_state.last_research_failure_time = datetime.now(timezone.utc)
                logger.warning("Strategist: Research Engine set to DEGRADED due to API failure.")
            return None

    def generate_new_strategy(self, instrument: str, granularity: str) -> Dict[str, Any]:
        """
        Uses an LLM to hypothesize a new trading strategy and validates it via backtest.
        """
        lessons = self._get_lessons()
        lessons_str = "\n".join([f"- {l}" for l in lessons]) if lessons else "No specific failures recorded yet."

        prompt = f"""
        You are a Quantitative Strategy Designer.
        Create a new deterministic trading strategy for {instrument} on {granularity} timeframe.

        PAST LESSONS TO INCORPORATE (Avoid these patterns):
        {lessons_str}

        The strategy must follow this strict JSON format:
        {{
            "version": "strat_v<unique_id>",
            "instrument": "{instrument}",
            "granularity": "{granularity}",
            "rules": {{
                "trigger": "one of [bullish_engulfing, bearish_engulfing, pin_bar, inside_bar]",
                "filters": [
                    {{ "indicator": "RSI", "operator": "<", "value": 30 }},
                    {{ "indicator": "SMA_200", "operator": ">", "value": 0 }}
                ]
            }}
        }}

        Ensure the rules are logically sound and directly address the lessons learned to avoid past mistakes.
        Return ONLY the JSON object.
        """

        strategy = self._call_llm(prompt)
        if not strategy:
            logger.warning("Strategist: LLM failed to generate strategy. Using fallback mock.")
            return self._generate_mock_strategy(instrument, granularity)

        # VALIDATION STEP: Backtest the proposed strategy before accepting it
        if self.backtester:
            logger.info(f"Strategist: Validating new hypothesis {strategy.get('version')} via backtest...")
            performance = self.backtester.run_backtest(strategy, instrument, granularity)

            # Fitness Gate: Only accept if viable (Profit Factor > 1.2)
            if performance.get('status') == 'Error' or performance.get('profit_factor', 0) < 1.2:
                logger.info(f"Strategist: Hypothesis {strategy.get('version')} failed backtest (PF: {performance.get('profit_factor', 0)}). Rejecting.")
                # Instead of rejecting entirely, we could ask the LLM to fix it,
                # but for now, we'll just try to generate another one.
                return self.generate_new_strategy(instrument, granularity)

        logger.info(f"Strategist: LLM generated and validated hypothesis {strategy.get('version')}")
        return strategy

    def optimize_strategy(self, strategy: Dict[str, Any], performance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Modifies an existing strategy's filters to improve performance using backtest data.
        """
        prompt = f"""
        You are a Strategy Optimization Engineer.
        Refine the following trading strategy to improve its performance.

        CURRENT STRATEGY:
        {json.dumps(strategy, indent=2)}

        HISTORICAL PERFORMANCE METRICS:
        {json.dumps(performance, indent=2)}

        TASK:
        Analyze the performance (Win Rate, Profit Factor, Max Drawdown) and adjust the filter values
        (e.g., RSI thresholds, SMA periods) to tighten entries and increase the win rate.
        Maintain the same JSON structure.
        Return ONLY the updated JSON object.
        """

        optimized = self._call_llm(prompt)
        if optimized:
            logger.info(f"Strategist: LLM optimized strategy {strategy.get('version')}")
            return optimized

        logger.warning(f"Strategist: LLM failed to optimize {strategy.get('version')}. Returning original.")
        return strategy

    def _generate_mock_strategy(self, instrument: str, granularity: str) -> Dict[str, Any]:
        import random
        triggers = ["bullish_engulfing", "bearish_engulfing", "pin_bar", "inside_bar"]
        version_id = random.randint(1000, 9999)
        return {
            "version": f"strat_{version_id}",
            "instrument": instrument,
            "granularity": granularity,
            "rules": {
                "trigger": random.choice(triggers),
                "filters": [
                    {"indicator": "RSI", "operator": "<", "value": 30 if random.random() > 0.5 else 70},
                    {"indicator": "SMA_200", "operator": ">", "value": 0}
                ]
            }
        }
