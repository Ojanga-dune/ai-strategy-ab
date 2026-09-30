import logging
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class PostMortemAgent:
    """
    The Evolutionary Loop Agent.
    Analyzes closed trades (especially losses) to extract generalized trading rules.
    """
    def __init__(self, trade_storage_dir: str = "data/trades", lessons_file: str = "data/lessons_learned.txt"):
        self.trade_storage_dir = Path(trade_storage_dir)
        self.lessons_file = Path(lessons_file)
        self.lessons_file.parent.mkdir(parents=True, exist_ok=True)

    def analyze_failure(self, trade_id: str, actual_outcome: Dict[str, Any]) -> str:
        """
        Uses an LLM to compare the 'Entry DNA' with the 'Actual Outcome'.
        Returns a concise 'Lesson Learned' string.
        """
        trade_dna_path = self.trade_storage_dir / f"{trade_id}.json"
        if not trade_dna_path.exists():
            return ""

        with open(trade_dna_path, 'r') as f:
            dna = json.load(f)

        # Construct the Post-Mortem Prompt
        prompt = f"""
        You are a Senior Trading Auditor. Analyze this failed trade to extract a generalized rule.

        ENTRY DNA:
        - Instrument: {dna.get('instrument')}
        - Entry Price: {dna.get('entry_price')}
        - AI Reasoning: {dna.get('ai_reasoning')}
        - Stop Loss: {dna.get('sl')}
        - Take Profit: {dna.get('tp')}

        ACTUAL OUTCOME:
        - Exit Price: {actual_outcome.get('exit_price', 'Unknown')}
        - PnL: {actual_outcome.get('pnl', 'Unknown')}
        - Outcome: {actual_outcome.get('status', 'LOSS')}

        TASK:
        Identify exactly why the AI's reasoning was wrong.
        Create a one-sentence 'Avoid' rule that is generalized enough to prevent similar losses
        but specific enough to be useful.

        Example: "Avoid buying XAU_USD if the 4H trend is bearish even if 15M shows a pin-bar."

        RESPONSE:
        Return ONLY the one-sentence rule.
        """

        # Simulation of LLM call (Replace with actual API call)
        # response = self.client.messages.create(...)
        lesson = f"Avoid {dna.get('instrument')} entries when {dna.get('ai_reasoning', 'reasoning')} fails to align with macro volatility."

        return lesson

    def register_lesson(self, lesson: str):
        """
        Saves the extracted rule to the evolutionary registry.
        """
        if not lesson:
            return

        with open(self.lessons_file, "a") as f:
            f.write(f"{lesson}\n")
        logger.info(f"Evolutionary Loop: New lesson registered: {lesson}")

    def run_evolutionary_cycle(self):
        """
        Scans the journal for recently closed loss trades and evolves the system.
        """
        logger.info("Starting Evolutionary Cycle...")
        # In a real implementation, we'd only analyze trades closed since the last cycle
        for trade_file in self.trade_storage_dir.glob("*.json"):
            with open(trade_file, 'r') as f:
                data = json.load(f)

            # Ensure pnl is a number for comparison
            pnl = data.get('pnl', 0)
            try:
                pnl_val = float(pnl) if pnl is not None else 0.0
            except (ValueError, TypeError):
                pnl_val = 0.0

            if data.get('status') == 'CLOSED' and pnl_val < 0:
                trade_id = trade_file.stem
                logger.info(f"Analyzing failed trade {trade_id}...")

                # In a real scenario, we'd fetch actual OANDA transaction data for the outcome
                outcome = {"exit_price": "Unknown", "pnl": -100, "status": "LOSS"}

                lesson = self.analyze_failure(trade_id, outcome)
                self.register_lesson(lesson)

        logger.info("Evolutionary Cycle complete.")
