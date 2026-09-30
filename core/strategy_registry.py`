import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import os

logger = logging.getLogger(__name__)

class StrategyRegistry:
    """
    Manages the collection of trading strategies per instrument.
    Tracks the current 'Champion' (live) and multiple 'Challengers' (shadow) for each asset.
    """
    def __init__(self, storage_file: str = "data/strategy_registry.json"):
        self.storage_path = Path(storage_file)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_registry()

    def _load_registry(self) -> Dict[str, Any]:
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load strategy registry: {e}")

        # Default structure: Keyed by instrument (e.g., "XAU_USD")
        return {}

    def _ensure_instrument_exists(self, instrument: str):
        """Initializes default strategies for an instrument if not already present."""
        if instrument not in self.data:
            logger.info(f"Initializing strategy registry for new instrument: {instrument}")
            self.data[instrument] = {
                "champion": {
                    "version": f"live_v1_{instrument}",
                    "instrument": instrument,
                    "granularity": "H1",
                    "rules": {
                        "trigger": "pin_bar",
                        "filters": []
                    },
                    "performance": {"win_rate": 0.0, "total_trades": 0, "pnl": 0.0, "wins": 0}
                },
                "challengers": []
            }
            self.save()

    def save(self):
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save strategy registry: {e}")

    def get_champion(self, instrument: str) -> Optional[Dict[str, Any]]:
        self._ensure_instrument_exists(instrument)
        return self.data[instrument]["champion"]

    def get_all_strategies(self, instrument: str) -> List[Dict[str, Any]]:
        """Returns a list of all strategies for a specific instrument, marking the champion."""
        self._ensure_instrument_exists(instrument)
        strategies = []
        champ = self.data[instrument]["champion"]
        strategies.append({**champ, "is_champion": True})

        for challenger in self.data[instrument]["challengers"]:
            strategies.append({**challenger, "is_champion": False})

        return strategies

    def add_challenger(self, strategy_json: Dict[str, Any]):
        """Adds a new strategy to the challenger pool for its specific instrument."""
        instrument = strategy_json.get("instrument", "XAU_USD")
        self._ensure_instrument_exists(instrument)

        version = strategy_json.get("version", "unknown")
        # Avoid duplicates for this instrument
        if any(c.get("version") == version for c in self.data[instrument]["challengers"]):
            logger.warning(f"Strategy {version} already exists in challengers for {instrument}.")
            return

        strategy_json["performance"] = {"win_rate": 0.0, "total_trades": 0, "pnl": 0.0, "wins": 0}
        self.data[instrument]["challengers"].append(strategy_json)
        self.save()
        logger.info(f"New Challenger strategy registered for {instrument}: {version}")

    def update_performance(self, instrument: str, version: str, pnl: float, is_win: bool, pnl_source: str = "estimated"):
        """Updates performance metrics for a specific strategy version within an instrument."""
        if pnl_source == "estimated":
            logger.debug(f"Skipping performance update for {version} (Estimated PnL).")
            return

        self._ensure_instrument_exists(instrument)

        # Check champion for this instrument
        if self.data[instrument]["champion"]["version"] == version:
            strat = self.data[instrument]["champion"]
        else:
            strat = next((c for c in self.data[instrument]["challengers"] if c.get("version") == version), None)

        if strat:
            perf = strat["performance"]
            perf["total_trades"] += 1
            perf["pnl"] += pnl
            wins = perf.get("wins", 0) + (1 if is_win else 0)
            perf["wins"] = wins
            perf["win_rate"] = wins / perf["total_trades"]
            self.save()

    def promote_challenger(self, instrument: str, version: str):
        """Promotes a challenger to the champion position for a specific instrument."""
        self._ensure_instrument_exists(instrument)
        challenger = next((c for c in self.data[instrument]["challengers"] if c.get("version") == version), None)
        if not challenger:
            logger.error(f"Challenger {version} not found for promotion in {instrument}.")
            return

        old_champ = self.data[instrument]["champion"]
        logger.info(f"PROMOTING STRATEGY for {instrument}: {version} is now the Champion. Replacing {old_champ['version']}.")

        self.data[instrument]["champion"] = challenger
        self.data[instrument]["challengers"] = [c for c in self.data[instrument]["challengers"] if c.get("version") != version]
        self.data[instrument]["challengers"].append(old_champ)

        self.save()

    def check_for_promotion(self, instrument: str) -> Optional[str]:
        """Evaluates challengers and promotes the best one if they meet reliability thresholds."""
        self._ensure_instrument_exists(instrument)
        best_challenger = None
        champ_win_rate = self.data[instrument]["champion"]["performance"].get("win_rate", 0.0)
        max_win_rate = -1.0

        for challenger in self.data[instrument]["challengers"]:
            perf = challenger["performance"]
            total_trades = perf.get("total_trades", 0)
            win_rate = perf.get("win_rate", 0.0)
            pnl = perf.get("pnl", 0.0)

            if total_trades >= 10:
                if win_rate > 0.60 or pnl > 0:
                    if win_rate > max_win_rate and win_rate > champ_win_rate:
                        max_win_rate = win_rate
                        best_challenger = challenger

        if best_challenger:
            version = best_challenger["version"]
            self.promote_challenger(instrument, version)
            return version
        return None
