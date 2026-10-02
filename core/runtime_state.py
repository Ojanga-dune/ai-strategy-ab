import logging
from datetime import datetime, timezone
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

class BotRuntimeState:
    """
    Tracks real-time bot metrics for monitoring and heartbeats.
    Initialized in live_main.py and passed to callbacks.
    """
    def __init__(self):
        self.startup_time = datetime.now(timezone.utc)
        self.cycle_count = 0
        self.last_cycle_timestamp = None
        self.last_heartbeat_time = None
        self.error_buffer = deque(maxlen=5)
        self.boot_count = 0

        # Heartbeat tracking
        self.heartbeat_pending = False
        self.heartbeat_due_at = None
        self.heartbeat_in_flight = False
        self.heartbeat_attempt_id = 0  # Generation ID to ignore stale futures
        self.heartbeat_send_deadline = None
        self.heartbeat_retry_count = 0
        self.next_retry_at = None
        self.current_heartbeat_future = None

        # Research Engine State
        self.research_engine_status = "HEALTHY"  # HEALTHY, DEGRADED
        self.last_research_failure_time = None

    def increment_cycle(self):
        self.cycle_count += 1
        self.last_cycle_timestamp = datetime.now(timezone.utc)

    def record_event(self, message: str):
        self.error_buffer.append(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}")

    def get_uptime_str(self) -> str:
        delta = datetime.now(timezone.utc) - self.startup_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m {seconds}s"
