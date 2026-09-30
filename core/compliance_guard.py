import logging
from typing import List, Tuple, Optional, Dict
from datetime import datetime, time

logger = logging.getLogger(__name__)

class ComplianceGuard:
    """
    Prop Firm Compliance Guard.
    Monitors account health and enforces hard limits to prevent account failure.
    """
    def __init__(self,
                 max_intraday_drawdown: float = 150.0,
                 daily_loss_limit: float = 500.0,
                 max_consecutive_losses: int = 3):
        self.max_intraday_drawdown = max_intraday_drawdown
        self.daily_loss_limit = daily_loss_limit
        self.max_consecutive_losses = max_consecutive_losses

        # State tracking
        self.start_of_day_equity = None
        self.consecutive_losses = 0
        self.kill_switch_active = False

    def update_daily_start(self, equity: float):
        """Sets the equity benchmark for the start of the trading day."""
        self.start_of_day_equity = equity
        self.consecutive_losses = 0
        self.kill_switch_active = False
        logger.info(f"ComplianceGuard: Daily benchmark set to ${equity:.2f}")

    def check_compliance(self, current_equity: float, current_pnl: float) -> Tuple[bool, str]:
        """
        Checks if the account is still within prop firm limits.
        Returns (is_compliant, reason).
        """
        if self.kill_switch_active:
            return False, "Kill switch is already active. Trading disabled."

        if self.start_of_day_equity is None:
            return True, "Benchmark not yet set"

        # 1. Intraday Drawdown Check
        drawdown = self.start_of_day_equity - current_equity
        if drawdown >= self.max_intraday_drawdown:
            self.kill_switch_active = True
            return False, f"HARD STOP: Intraday drawdown (${drawdown:.2f}) hit limit (${self.max_intraday_drawdown})"

        # 2. Daily Loss Limit Check
        if current_pnl <= -self.daily_loss_limit:
            self.kill_switch_active = True
            return False, f"HARD STOP: Daily loss limit (${current_pnl:.2f}) hit limit (${self.daily_loss_limit})"

        # 3. Consecutive Loss Check
        if self.consecutive_losses >= self.max_consecutive_losses:
            return False, f"PAUSE: Max consecutive losses ({self.consecutive_losses}) reached."

        return True, "Compliant"

    def record_trade_outcome(self, is_win: bool):
        """Updates consecutive loss counter based on trade outcome."""
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            logger.warning(f"ComplianceGuard: Consecutive losses increased to {self.consecutive_losses}")

class SessionFilter:
    """
    Enforces trading window restrictions.
    Prevents entries outside of defined high-probability session hours.
    """
    def __init__(self, sessions: List[Dict] = None):
        """
        sessions: List of dicts with {'name': str, 'start': time, 'end': time, 'days': List[int]}
        Default: London/NY overlap (approx 8am to 5pm UTC)
        """
        if sessions is None:
            self.sessions = [
                {
                    'name': 'Main Session',
                    'start': time(8, 0),
                    'end': time(17, 0),
                    'days': [0, 1, 2, 3, 4] # Mon-Fri
                }
            ]
        else:
            self.sessions = sessions

    def is_trade_allowed(self) -> Tuple[bool, str]:
        """
        Checks if the current UTC time falls within any allowed session.
        """
        now = datetime.utcnow()
        current_time = now.time()
        current_day = now.weekday()

        for session in self.sessions:
            if current_day in session['days']:
                if session['start'] <= current_time <= session['end']:
                    return True, f"Within {session['name']} session."

        return False, "Outside of allowed trading sessions."

class CandleGuard:
    """
    Prevents 'Painting' (Repainting) by ensuring signals are only
    acted upon AFTER a candle has officially closed.
    """
    @staticmethod
    def is_candle_closed(last_candle_time: datetime, granularity_seconds: int) -> bool:
        """
        Verifies if the last candle timestamp is old enough to be considered closed.
        """
        now = datetime.utcnow()
        # If current time is past the (start of candle + duration), the candle is closed.
        if (now - last_candle_time).total_seconds() >= granularity_seconds:
            return True
        return False
