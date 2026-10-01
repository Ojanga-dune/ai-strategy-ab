import logging
from typing import List, Tuple, Optional, Dict
from datetime import datetime, time
import math
try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

logger = logging.getLogger(__name__)

class ComplianceGuard:
    """
    Prop Firm Compliance Guard.
    Monitors account health and enforces hard limits to prevent account failure.
    """
    def __init__(self,
                 max_intraday_drawdown: float = 150.0,
                 daily_loss_limit: float = 500.0,
                 max_consecutive_losses: int = 3,
                 daily_reset_tz: str = "America/New_York",
                 daily_reset_time: time = time(17, 0)):
        self.max_intraday_drawdown = max_intraday_drawdown
        self.daily_loss_limit = daily_loss_limit
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_reset_tz = daily_reset_tz
        self.daily_reset_time = daily_reset_time

        # State tracking
        self.start_of_day_equity = None
        self.consecutive_losses = 0
        self.kill_switch_active = False
        self._last_reset_date = None

    def _should_reset_daily_stats(self) -> bool:
        """Checks if the current time has passed the daily reset window in the target timezone."""
        tz = zoneinfo.ZoneInfo(self.daily_reset_tz)
        now_tz = datetime.now(tz)

        # Today's reset point
        today_reset = datetime.combine(now_tz.date(), self.daily_reset_time).replace(tzinfo=tz)

        # If now is after today's reset, and we haven't reset today, or we are in a new calendar day
        if now_tz >= today_reset:
            # Reset if we haven't reset yet for this date
            if self._last_reset_date != now_tz.date():
                return True
        return False

    def update_daily_start(self, equity: float):
        """Sets the equity benchmark for the start of the trading day."""
        if equity is None or equity <= 0:
            logger.warning(f"ComplianceGuard: Refusing to set daily benchmark to invalid value: {equity}")
            return

        # Handle automatic reset based on timezone/time
        if self._should_reset_daily_stats():
            tz = zoneinfo.ZoneInfo(self.daily_reset_tz)
            now_tz = datetime.now(tz)
            self._last_reset_date = now_tz.date()
            logger.info(f"ComplianceGuard: Daily reset triggered ({self.daily_reset_tz} {self.daily_reset_time})")

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

        if current_equity is None or current_equity <= 0 or math.isnan(current_equity) or math.isinf(current_equity):
            return True, "Invalid Account State: Equity unavailable or non-positive (New entries blocked, positions preserved)"

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
        Checks if the current UTC time falls within any allowed session
        and ensures the market is open (not in weekend gap).
        """
        # 1. Market Hours Check (NY Time)
        try:
            import zoneinfo
        except ImportError:
            from backports import zoneinfo

        ny_tz = zoneinfo.ZoneInfo("America/New_York")
        now_ny = datetime.now(ny_tz)
        weekday = now_ny.weekday() # Mon=0, Sun=6
        hour = now_ny.hour

        # Friday after 17:00 NY
        if weekday == 4 and hour >= 17:
            return False, "Market closed for weekend (Friday 17:00 NY)"
        # Saturday
        if weekday == 5:
            return False, "Market closed for weekend (Saturday)"
        # Sunday before 17:00 NY
        if weekday == 6 and hour < 17:
            return False, "Market closed for weekend (Sunday < 17:00 NY)"

        # 2. Session Filter Check (UTC)
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
