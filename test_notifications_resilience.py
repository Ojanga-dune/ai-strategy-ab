import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
import threading
import time
from telegram.error import Forbidden, InvalidToken, NetworkError, TimedOut
from core.notifications import NotificationManager

class TestNotificationsResilience(unittest.TestCase):
    def setUp(self):
        self.token = "test_token"
        self.chat_id = "12345"
        self.notifier = NotificationManager(token=self.token, chat_id=self.chat_id)

    def test_initialization_normal(self):
        """Verify normal initialization."""
        self.assertEqual(self.notifier.token, self.token)
        self.assertFalse(self.notifier._is_permanently_disabled)

    def test_initialization_missing_creds(self):
        """Verify that missing credentials disable notifications safely."""
        notifier = NotificationManager(token=None, chat_id=None)
        self.assertTrue(notifier._is_permanently_disabled)

    @patch('core.notifications.Bot')
    def test_send_message_success(self, mock_bot_class):
        """Verify send_message calls bot.send_message."""
        mock_bot = mock_bot_class.return_value
        mock_bot.send_message = AsyncMock()

        self.notifier.bot = mock_bot
        asyncio.run(self.notifier.send_message("Hello"))
        mock_bot.send_message.assert_called_once_with(chat_id=self.chat_id, text="Hello")

    @patch('core.notifications.Bot')
    def test_send_message_unauthorized(self, mock_bot_class):
        """Verify that Unauthorized error permanently disables notifications."""
        mock_bot = mock_bot_class.return_value
        mock_bot.send_message = AsyncMock(side_effect=Forbidden("Invalid token"))

        self.notifier.bot = mock_bot
        asyncio.run(self.notifier.send_message("Hello"))
        self.assertTrue(self.notifier._is_permanently_disabled)

    @patch('core.notifications.Bot')
    def test_send_message_transient_failure(self, mock_bot_class):
        """Verify that transient errors are logged but not fatal."""
        mock_bot = mock_bot_class.return_value
        mock_bot.send_message = AsyncMock(side_effect=NetworkError("Timeout"))

        self.notifier.bot = mock_bot
        asyncio.run(self.notifier.send_message("Hello"))
        self.assertFalse(self.notifier._is_permanently_disabled)

    def test_send_sync_isolation(self):
        """Verify that send_sync does not propagate exceptions to the main thread."""
        self.notifier.bot = MagicMock()
        # Force an exception inside the sync send
        # Need to mock the async function it calls
        self.notifier.bot.send_message = AsyncMock(side_effect=Exception("Crash!"))

        # This should not raise an exception
        try:
            self.notifier.send_sync("This should not crash the bot")
            time.sleep(0.1) # Give thread a moment to run
        except Exception as e:
            self.fail(f"send_sync propagated exception: {e}")

    def test_stop_listener(self):
        """Verify stop_listener sets the stop event."""
        self.notifier.stop_listener()
        self.assertTrue(self.notifier._stop_event.is_set())

if __name__ == "__main__":
    unittest.main()
