import logging
import asyncio
import threading
import time
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import TelegramError, Forbidden, InvalidToken, NetworkError, TimedOut
from typing import Optional, Callable, Dict, Any
import math

logger = logging.getLogger(__name__)

class NotificationManager:
    """
    Handles outgoing alerts and incoming commands from Telegram.
    Designed to be non-fatal: failures here must not crash the trading engine.
    """
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token
        self.chat_id = chat_id
        self.bot = None

        # Storage for command callbacks to be set by the orchestrator (live_main.py)
        self.callbacks: Dict[str, Callable] = {}
        self._app = None
        self._thread = None
        self._stop_event = threading.Event()
        self._is_permanently_disabled = False

        if not token or not chat_id:
            logger.warning("Telegram credentials missing. Notifications and Command Control are disabled.")
            self._is_permanently_disabled = True
        else:
            try:
                # Test connection/token validity during init
                self.bot = Bot(token=token)
                # We don't call get_me() here to avoid blocking startup,
                # the listener will handle validation.
            except Exception as e:
                logger.error(f"Initial Telegram Bot creation failed: {e}")
                self._is_permanently_disabled = True

    async def send_message(self, text: str):
        """Sends a message to the configured Telegram chat."""
        if self._is_permanently_disabled or not self.bot or not self.chat_id:
            logger.info(f"[NOTIFICATION-DISABLED] {text}")
            return

        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text)
        except (Forbidden, InvalidToken):
            logger.critical("Telegram token is unauthorized or invalid. Disabling notifications permanently.")
            self._is_permanently_disabled = True
        except (NetworkError, TimedOut) as e:
            logger.warning(f"Transient Telegram error while sending: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram notification: {e}")

    def send_sync(self, text: str):
        """Synchronous wrapper for sending messages. Spawns a daemon thread to prevent blocking."""
        if self._is_permanently_disabled or not self.bot or not self.chat_id:
            logger.info(f"[NOTIFICATION-DISABLED] {text}")
            return

        def _send():
            try:
                # Each sync send gets its own temporary event loop to avoid conflicts
                asyncio.run(self.send_message(text))
            except Exception as e:
                logger.error(f"Async send failure in background thread: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def register_callback(self, command: str, callback: Callable):
        """Allows the bot to register a function to be called when a Telegram command is received."""
        self.callbacks[command] = callback
        logger.info(f"Registered Telegram callback for command: {command}")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Internal handler for incoming Telegram messages."""
        if not update.message or not update.message.text:
            return

        text = update.message.text
        if text.startswith('/'):
            cmd_part = text.split()[0]
            cmd = cmd_part[1:].lower().strip()

            if cmd in self.callbacks:
                try:
                    response = self.callbacks[cmd](text, context)
                    if response:
                        await self.send_message(response)
                except Exception as e:
                    logger.error(f"Error executing command {cmd}: {e}")
                    await self.send_message(f"❌ Error executing {cmd}: {str(e)}")
            else:
                available = ', '.join([c for c in self.callbacks.keys() if c != 'message'])
                await self.send_message(f"Unknown command: {cmd}. Available: {available}")
        else:
            if 'message' in self.callbacks:
                try:
                    response = self.callbacks['message'](text, context)
                    if response:
                        await self.send_message(response)
                except Exception as e:
                    logger.error(f"Error executing message callback: {e}")

    def start_listener(self):
        """Starts the Telegram bot listener in a background thread with resilience."""
        if not self.token or self._is_permanently_disabled:
            return

        def _run_bot_with_retry():
            retry_delay = 5
            max_delay = 300

            while not self._stop_event.is_set():
                try:
                    logger.info("Attempting to start Telegram Command Listener...")
                    # Build application
                    self._app = ApplicationBuilder().token(self.token).build()

                    # Register handlers
                    self._app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_message))
                    self._app.add_handler(MessageHandler(filters.COMMAND, self._handle_message))

                    logger.info("Telegram Command Listener connected and polling...")
                    # reset retry delay on success
                    retry_delay = 5

                    # run_polling is blocking
                    self._app.run_polling(close_loop=False)

                except (Forbidden, InvalidToken):
                    logger.critical("Telegram Listener: Token is unauthorized or invalid. Disabling Telegram permanently.")
                    self._is_permanently_disabled = True
                    break
                except (NetworkError, TimedOut) as e:
                    logger.warning(f"Telegram Listener: Transient network error ({e}). Retrying in {retry_delay}s...")
                    # Use stop_event.wait instead of time.sleep to allow immediate shutdown
                    if self._stop_event.wait(timeout=retry_delay):
                        break
                    retry_delay = min(retry_delay * 2, max_delay)
                except Exception as e:
                    logger.error(f"Telegram Listener: Unexpected crash ({e}). Restarting in {retry_delay}s...")
                    if self._stop_event.wait(timeout=retry_delay):
                        break
                    retry_delay = min(retry_delay * 2, max_delay)
                finally:
                    # Cleanup app instance before retry to avoid resource leaks
                    self._app = None

        self._thread = threading.Thread(target=_run_bot_with_retry, daemon=True)
        self._thread.start()

    def stop_listener(self):
        """Stops the Telegram bot listener gracefully."""
        logger.info("Stopping Telegram Listener...")
        self._stop_event.set()
        if self._app:
            try:
                # Note: Application.stop is async. In a background thread,
                # we rely on the thread being daemonized or the loop being closed.
                # For a cleaner stop, we'd need to manage the loop explicitly.
                pass
            except Exception as e:
                logger.error(f"Error during Telegram listener stop: {e}")
