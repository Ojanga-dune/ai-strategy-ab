import logging
import time
import uuid
from typing import Dict, Any, Callable, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class PortfolioManager:
    """
    The 'Health Monitor': Monitors overall account exposure and manages
    interactive consultations for risk reduction.
    """
    def __init__(
        self,
        critical_loss_threshold: float = -0.02,  # -2% Drawdown
        profit_lock_threshold: float = 0.05,    # +5% Profit
        consultation_timeout_mins: int = 30
    ):
        self.critical_loss_threshold = critical_loss_threshold
        self.profit_lock_threshold = profit_lock_threshold
        self.consultation_timeout_mins = consultation_timeout_mins

        # Stores pending user decisions: { consultation_id: { "action": Callable, "args": List, "timestamp": float, "prompt": str } }
        self.pending_consultations: Dict[str, Dict[str, Any]] = {}

    def check_health(self, exchange, notifier):
        """
        Analyzes overall portfolio PnL and triggers consultations if thresholds are breached.
        """
        try:
            positions = exchange.get_open_positions()
            if not positions:
                return

            summary = exchange.get_account_summary()
            balance = float(summary.get('balance', 0))
            if balance == 0:
                logger.warning("Account balance is 0. Cannot calculate PnL percentage.")
                return

            # Sum unrealized PnL from all open positions
            total_unrealized_pnl = 0.0
            for p in positions:
                pnl_str = p.get('unrealizedPL', '0.0')
                try:
                    total_unrealized_pnl += float(pnl_str)
                except (ValueError, TypeError):
                    continue

            pnl_pct = total_unrealized_pnl / balance
            logger.info(f"Portfolio Health Check: Total Unrealized PnL: ${total_unrealized_pnl:.2f} ({pnl_pct:.2%})")

            if pnl_pct <= self.critical_loss_threshold:
                self._trigger_consultation(
                    notifier,
                    reason="CRITICAL LOSS",
                    current_val=pnl_pct,
                    action_name="Close 50% of positions",
                    action_func=self._close_half_positions,
                    action_args=[exchange]
                )
            elif pnl_pct >= self.profit_lock_threshold:
                self._trigger_consultation(
                    notifier,
                    reason="PROFIT LOCK",
                    current_val=pnl_pct,
                    action_name="Lock in gains (Close 50%)",
                    action_func=self._close_half_positions,
                    action_args=[exchange]
                )
        except Exception as e:
            logger.error(f"Error during portfolio health check: {e}", exc_info=True)

    def _trigger_consultation(self, notifier, reason: str, current_val: float, action_name: str, action_func: Callable, action_args: List):
        """
        Generates a unique ID and sends a prompt to the user.
        """
        cons_id = f"CONS_{uuid.uuid4().hex[:6].upper()}"

        prompt = (
            f"⚠️ **{reason} ALERT**\n"
            f"Portfolio PnL: {current_val:.2%}\n"
            f"Suggested Action: {action_name}\n\n"
            f"Reply `YES {cons_id}` to confirm or `NO {cons_id}` to ignore."
        )

        self.pending_consultations[cons_id] = {
            "action": action_func,
            "args": action_args,
            "timestamp": time.time(),
            "prompt": prompt
        }

        notifier.send_sync(prompt)
        logger.info(f"Consultation {cons_id} triggered for {reason}.")

    def handle_response(self, text: str, context: Any = None) -> Optional[str]:
        """
        Callback for NotificationManager to route YES/NO responses.
        """
        text_upper = text.upper().strip()
        parts = text_upper.split()

        if len(parts) < 2:
            return None

        answer = parts[0] # YES or NO
        cons_id = parts[1]

        if cons_id not in self.pending_consultations:
            return None

        consultation = self.pending_consultations[cons_id]

        # Check for timeout
        if time.time() - consultation['timestamp'] > (self.consultation_timeout_mins * 60):
            del self.pending_consultations[cons_id]
            return f"❌ Consultation {cons_id} has expired."

        if answer == "YES":
            try:
                action = consultation['action']
                args = consultation['args']
                # Execute the action
                result_msg = action(*args)
                del self.pending_consultations[cons_id]
                return f"✅ Action executed for {cons_id}: {result_msg}"
            except Exception as e:
                logger.error(f"Error executing consultation action {cons_id}: {e}")
                return f"❌ Failed to execute action for {cons_id}: {str(e)}"

        elif answer == "NO":
            del self.pending_consultations[cons_id]
            return f"ℹ️ Consultation {cons_id} ignored by user."

        return None

    def _close_half_positions(self, exchange) -> str:
        """
        Corrective action: Closes 50% of all open positions.
        """
        positions = exchange.get_open_positions()
        if not positions:
            return "No open positions to close."

        closed_count = 0
        total_units_closed = 0

        for p in positions:
            instrument = p.get('instrument')
            # Get net units
            long_units = float(p.get('long', {}).get('units', 0))
            short_units = float(p.get('short', {}).get('units', 0))
            net_units = long_units - short_units

            if net_units == 0:
                continue

            # Close 50% (round down to nearest integer)
            units_to_close = -int(net_units * 0.5)
            if units_to_close == 0:
                continue

            result = exchange.place_market_order(instrument, units_to_close)
            if 'orderCreateTransaction' in result:
                closed_count += 1
                total_units_closed += abs(units_to_close)

        return f"Closed 50% of {closed_count} positions (Total units: {total_units_closed})."
