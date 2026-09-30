import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import pandas as pd

logger = logging.getLogger(__name__)

class BrokerInterface(ABC):
    """
    Abstract Base Class for all Broker connections.
    Ensures that the LiveBot can swap between OANDA, MT5, or Prop Firm APIs
    without changing the core logic.
    """

    @abstractmethod
    def get_latest_candles(self, instrument: str, granularity: str, count: int = 100) -> pd.DataFrame:
        """Fetch historical candles."""
        pass

    @abstractmethod
    def get_mtf_candles(self, instrument: str, granularities: List[str], count: int = 100) -> Dict[str, pd.DataFrame]:
        """Fetch candles for multiple timeframes."""
        pass

    @abstractmethod
    def place_market_order(self, instrument: str, lots: float, stop_loss: float = None, take_profit: float = None) -> Dict[str, Any]:
        """Place a market order using lot sizes."""
        pass

    @abstractmethod
    def get_account_summary(self) -> Dict[str, Any]:
        """Get balance, equity, and margin."""
        pass

    @abstractmethod
    def get_open_positions(self, instrument: str = None) -> List[Dict[str, Any]]:
        """List all open positions."""
        pass

    @abstractmethod
    def close_position(self, trade_id: str) -> Dict[str, Any]:
        """Close a specific position by ID."""
        pass

    @abstractmethod
    def modify_order(self, trade_id: str, stop_loss: float = None, take_profit: float = None) -> Dict[str, Any]:
        """Modify SL or TP of an existing order."""
        pass

    @abstractmethod
    def get_market_price(self, instrument: str) -> Dict[str, float]:
        """Get current Bid and Ask prices separately."""
        pass
