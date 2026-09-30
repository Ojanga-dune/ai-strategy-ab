import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Ensures all trades adhere to account safety guardrails and calculates optimal position size.
    """
    def __init__(
        self,
        risk_per_trade: float = 0.01,
        max_open_trades: int = 3,
        daily_drawdown_limit: float = 0.02,
        default_stop_loss_pips: float = 20.0
    ):
        self.risk_per_trade = risk_per_trade          # e.g., 0.01 for 1%
        self.max_open_trades = max_open_trades
        self.daily_drawdown_limit = daily_drawdown_limit
        self.default_stop_loss_pips = default_stop_loss_pips

    def calculate_position_size(
        self,
        account_balance: Any,
        entry_price: float,
        stop_loss: float,
        instrument: str = "XAU_USD"
    ) -> float:
        """
        Calculates the position size in LOTS based on risk percentage and distance to SL.
        1 Lot = 100 oz for XAU_USD, 100,000 units for most Forex.
        """
        if stop_loss is None or entry_price == stop_loss:
            logger.warning("Invalid entry or SL for position sizing. Using minimum lot (0.01).")
            return 0.01

        # 1. Robustly handle balance (OANDA often returns strings)
        try:
            balance = float(account_balance)
        except (ValueError, TypeError):
            logger.warning(f"Could not parse balance '{account_balance}', using fallback $10,000")
            balance = 10000.0

        # 2. Calculate total dollar risk
        risk_amount = balance * self.risk_per_trade

        # 3. Calculate distance to stop loss
        price_diff = abs(entry_price - stop_loss)

        if price_diff == 0:
            return 0.0

        # 4. Calculate units first: Risk / Price distance
        units = risk_amount / price_diff

        # 5. Convert Units to Lots
        unit_multiplier = 100 if "XAU" in instrument.upper() else 100000
        lots = units / unit_multiplier

        logger.info(f"Sizing Calculation: Balance ${balance:.2f}, Risk ${risk_amount:.2f}, Diff {price_diff:.2f} -> Units {units:.2f} -> Lots {lots:.3f}")

        return max(lots, 0.01) if lots != 0 else 0.0

    def check_daily_drawdown(self, current_balance: float, start_of_day_balance: float) -> bool:
        """
        Returns False if the account has lost more than daily_drawdown_limit.
        """
        if start_of_day_balance == 0:
            return True

        drawdown = (start_of_day_balance - current_balance) / start_of_day_balance
        if drawdown > self.daily_drawdown_limit:
            logger.error(f"Daily drawdown limit reached: {drawdown:.2%}")
            return False
        return True

    def can_trade(
        self,
        current_positions: List,
        current_balance: float,
        start_of_day_balance: float
    ) -> Tuple[bool, str]:
        """
        Aggregated safety check. Returns (Allowed, Reason).
        """
        try:
            balance = float(current_balance)
        except:
            balance = 0.0

        if len(current_positions) >= self.max_open_trades:
            return False, f"Max open trades limit ({self.max_open_trades}) reached."

        if not self.check_daily_drawdown(balance, start_of_day_balance):
            return False, "Daily drawdown limit exceeded. Trading halted."

        return True, "Risk checks passed."
