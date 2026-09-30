import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
import requests

logger = logging.getLogger(__name__)

class NewsGuard:
    """
    Handles News Compliance and Spread Filtering.
    Prevents trading during high-volatility events where spreads widen.
    """
    def __init__(self, max_allowed_spread: float = 0.50):
        """
        max_allowed_spread: The maximum difference between Ask and Bid
        allowed for an entry. For XAU_USD, 0.50 would be $0.50.
        """
        self.max_allowed_spread = max_allowed_spread
        self._news_cache = []
        self._last_cache_time = None

    def check_spread(self, bid: float, ask: float, instrument: str) -> Tuple[bool, str]:
        """
        Calculates the current spread and determines if it is too wide.
        """
        spread = ask - bid

        if spread > self.max_allowed_spread:
            return False, f"Spread too wide: {spread:.3f} (Limit: {self.max_allowed_spread:.3f})"

        return True, f"Spread acceptable: {spread:.3f}"

    def is_news_event_active(self, api_key: str, account_id: str) -> Tuple[bool, str]:
        """
        Checks OANDA's news endpoint to see if a high-impact event is occurring.
        Blocks trading if a high-impact event is within +/- 30 mins of now.
        """
        # Use timezone-aware UTC now
        now = datetime.now(timezone.utc)

        # Cache news for 1 hour to avoid hitting API every cycle
        if self._last_cache_time and (now - self._last_cache_time).total_seconds() < 3600:
            news_calendar = self._news_cache
        else:
            try:
                # OANDA v20 News Endpoint (Practice/Demo)
                # We use the account-specific news endpoint if available,
                # otherwise a general market news endpoint.
                url = f"https://api-fxpractice.oanda.com/v3/accounts/{account_id}/news"
                headers = {"Authorization": f"Bearer {api_key}"}
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code == 200:
                    # OANDA returns news in a 'news' list or directly as a list
                    data = response.json()
                    self._news_cache = data.get('news', data) if isinstance(data, dict) else data
                    self._last_cache_time = now
                    news_calendar = self._news_cache
                elif response.status_code == 404:
                    logger.warning("News endpoint not found for this account. Using default allowed.")
                    return False, "News endpoint not found, allowing trade."
                else:
                    logger.warning(f"Failed to fetch news: {response.status_code} - {response.text}")
                    return False, "News API unavailable, allowing trade by default."
            except Exception as e:
                logger.error(f"News API request failed: {e}")
                return False, "News API error, allowing trade by default."

        if not news_calendar or not isinstance(news_calendar, list):
            return False, "No news calendar available."

        # Check for high-impact events within 30 minutes (1800 seconds)
        for event in news_calendar:
            if not isinstance(event, dict):
                continue

            impact = str(event.get('impact', '')).upper()
            # We strictly block on 'HIGH' impact events.
            if impact == 'HIGH' or impact == '3' or impact == 'CRITICAL':
                try:
                    event_time_str = event.get('time')
                    if not event_time_str:
                        continue

                    # Handle ISO 8601 formats (e.g., 2023-10-27T14:00:00Z)
                    # Use fromisoformat for better compatibility with OANDA's Z suffix
                    event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))

                    if abs((now - event_time).total_seconds()) <= 1800:
                        return True, f"HIGH IMPACT NEWS: {event.get('headline', 'Unknown')} at {event_time_str}"
                except Exception as e:
                    logger.debug(f"Error parsing news time {event.get('time')}: {e}")
                    continue

        return False, "No high-impact news detected."
