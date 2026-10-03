import pytest
import asyncio
import threading
import time
from unittest.mock import MagicMock, patch
from core.notifications import NotificationManager

def test_telegram_conflict_exception_handling():
    """
    TARGETED TEST: Specifically trigger the telegram.error.Conflict path
    to verify no NameError (telegram or os) and correct state transition.
    """
    # Setup manager
    nm = NotificationManager(token="valid", chat_id="123")
    
    # We need to mock ApplicationBuilder().token().build().run_polling()
    # to raise the Conflict error immediately.
    with patch('core.notifications.ApplicationBuilder') as mock_builder:
        mock_app = MagicMock()
        # Mock run_polling to raise Conflict
        import telegram
        mock_app.run_polling.side_effect = telegram.error.Conflict("Conflict!")
        mock_builder.return_value.token.return_value.build.return_value = mock_app
        
        # Start listener in a separate thread to avoid blocking
        nm.start_listener()
        
        # Give it a moment to hit the exception
        time.sleep(1)
        
        # VERIFICATIONS
        # 1. Check state transition
        assert nm.state == "CONFLICT", f"Expected state CONFLICT, got {nm.state}"
        
        # 2. Ensure the thread is still alive (meaning it didn't crash with NameError)
        # If it crashed with NameError, the loop would terminate or the thread would die
        # depends on where the error happened.
        assert nm._thread.is_alive(), "Listener thread died unexpectedly (likely a NameError)"
        
        # Cleanup
        nm.stop_listener()

if __name__ == "__main__":
    pytest.main([__file__])
