import pandas as pd
import numpy as np
import logging
import json
from typing import List, Dict, Any
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIReviewer:
    """
    The 'Brain': Pass 2 of the hybrid backtester.
    Takes Candidate Signals from the StrategyEngine and performs a contextual,
    qualitative analysis using an LLM (Claude) to filter out low-probability setups.
    """
    def __init__(self, api_key=None):
        self.api_key = api_key
        # In a real implementation, we would initialize the Anthropic client here
        # self.client = anthropic.Anthropic(api_key=api_key)

    def _prepare_context_window(self, df: pd.DataFrame, index: int, window_size: int = 20) -> str:
        """
        Slices the dataframe around the signal and converts it to a text format
        the LLM can interpret as a 'chart'.
        """
        start = max(0, index - window_size)
        end = min(len(df), index + 1)
        window = df.iloc[start:end]

        # Convert OHLC data to a human-readable string for the LLM
        # We provide the last 20 candles leading up to the signal
        context_str = "Time | Open | High | Low | Close | Volume\n"
        context_str += "-" * 50 + "\n"

        for ts, row in window.iterrows():
            marker = " <--- SIGNAL" if ts == df.index[index] else ""
            context_str += f"{ts} | {row['open']:.2f} | {row['high']:.2f} | {row['low']:.2f} | {row['close']:.2f} | {row['volume']}{marker}\n"

        return context_str

    def validate_signals(self, candidates: List[Dict[str, Any]], datalake: Any, confluence: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Filters candidates through the LLM.
        """
        if not candidates:
            return []

        # Load active lessons from the evolutionary registry
        lessons = self._get_active_lessons()

        # We need the dataframe to extract the context windows
        # Assuming all candidates are for the same instrument/granularity for this batch
        instrument = candidates[0]['instrument']
        granularity = candidates[0]['granularity']
        df = datalake.load_data(instrument, granularity)

        verified_trades = []

        logger.info(f"AI Reviewer: Processing {len(candidates)} candidates with MTF confluence...")

        for candle in candidates:
            context = self._prepare_context_window(df, candle['context_window'])

            # Construct the prompt for Claude including MTF confluence and past lessons
            prompt = self._build_review_prompt(candle, context, confluence, lessons)

            # Simulate LLM call (Replace with actual API call)
            # response = self.client.messages.create(model="claude-3-5-sonnet", messages=[...])
            is_approved, reasoning = self._simulate_llm_call(prompt)

            if is_approved:
                logger.info(f"Trade Approved at {candle['timestamp']}: {reasoning}")
                candle['ai_reasoning'] = reasoning
                verified_trades.append(candle)
            else:
                logger.debug(f"Trade Rejected at {candle['timestamp']}")

        logger.info(f"AI Review completed. {len(verified_trades)}/{len(candidates)} approved.")
        return verified_trades

    def _get_active_lessons(self) -> List[str]:
        """
        Retrieves the latest lessons learned from the evolutionary registry.
        """
        lessons_path = Path("data/lessons_learned.txt")
        if not lessons_path.exists():
            return []

        with open(lessons_path, "r") as f:
            lessons = [line.strip() for line in f.readlines() if line.strip()]

        # Return the last 5 lessons to avoid prompt bloating
        return lessons[-5:]

    def _build_review_prompt(self, candle: Dict, context: str, confluence: Dict[str, Any] = None, lessons: List[str] = None) -> str:
        """
        Builds a professional trading prompt for Claude.
        """
        lessons_str = "\n".join([f"- {l}" for l in lessons]) if lessons else "No specific past failures recorded for this instrument."

        confluence_str = "Not provided"
        if confluence:
            # If confluence is the summary object from StrategyEngine.evaluate_confluence
            trend_align = confluence.get('trend_alignment', 'Unknown')
            precision = confluence.get('precision_entry', 'Unknown')
            confluence_str = f"Trend Alignment: {trend_align}, Entry Precision: {precision}"

            # If there are specific timeframe details, append them
            details = confluence.get('details', {})
            if details:
                details_str = "\n".join([f"{k}: {v}" for k, v in details.items()])
                confluence_str += f"\nDetails:\n{details_str}"

        return f"""
        You are an expert Quantitative Price Action Trader.
        Review the following candidate signal and decide if it is high-probability.

        INSTRUMENT: {candle['instrument']}
        PATTERN: {candle['trigger']}
        PRICE AT SIGNAL: {candle['price']}

        MULTI-TIMEFRAME CONFLUENCE:
        {confluence_str}

        RECENT PRICE ACTION ({candle['granularity']}):
        {context}

        PAST FAILURES (LESSONS LEARNED):
        {lessons_str}

        CRITERIA FOR APPROVAL:
        1. Is the signal occurring at a logical structural level (Support/Resistance/Supply/Demand)?
        2. Is there a clear trend alignment across multiple timeframes (HTF trend matches signal)?
        3. Does this setup avoid the patterns identified in 'PAST FAILURES'?
        4. Is the risk-to-reward ratio favorable based on the recent range?

        RESPONSE FORMAT:
        Return ONLY a JSON object:
        {{
            "approved": true/false,
            "reasoning": "Short explanation of the decision, explicitly mentioning confluence and lessons learned"
        }}
        """

    def _simulate_llm_call(self, prompt: str) -> (bool, str):
        """
        Simulation of the LLM response for scaffolding.
        In production, this is replaced by a call to the Claude API.
        """
        # For simulation, we approve 30% of trades to test the pipeline
        import random
        approved = random.random() < 0.3
        reasoning = "Strong structural alignment with bullish trend" if approved else "Lack of volume confirmation"
        return approved, reasoning
