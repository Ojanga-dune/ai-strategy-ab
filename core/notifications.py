import logging
import asyncio
import threading
import time
import telegram
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
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None, runtime_state: Any = None):
        self.token = token
        self.chat_id = chat_id
        self.bot = None
        self.runtime_state = runtime_state

        # Storage for command callbacks to be set by the orchestrator (live_main.py)
        self.callbacks: Dict[str, Callable] = {}
        self._app = None
        self._thread = None
        self._loop = None
        self._stop_event = threading.Event()
        self._is_permanently_disabled = False
        self.state = "STOPPED" # STOPPED, STARTING, RUNNING, DEGRADED, RECONNECTING, STOPPING, CONFLICT
, CONFLICT
        self.polling_generation_id = 0

        # Storage for command callbacks to be set by the orchestrator (live_main.py)
        self.callbacks: Dict[str, Callable] = {}
        self._app = None
        self._thread = None
        self._loop = None
        self._stop_event = threading.Event()
        self._is_permanently_disabled = False
        self.state = "STOPPED" # STOPPED, STARTING, RUNNING, DEGRADED, RECONNECTING, STOPPING, CONFLICT


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

    def send_sync(self, text: str) -> Optional[asyncio.Future]:
        """Synchronous wrapper for sending messages. Schedules task on the authoritative loop.
        Returns the Future representing the delivery attempt.
        """
        if self._is_permanently_disabled or not self.bot or not self.chat_id:
            logger.info(f"[NOTIFICATION-DISABLED] {text}")
            return None

        if self.state == "STOPPED" or self.state == "STOPPING":
            logger.warning(f"Notification skipped: Telegram is {self.state}")
            return None

        if self._loop and self._loop.is_running():
            try:
                return asyncio.run_coroutine_threadsafe(self.send_message(text), self._loop)
            except Exception as e:
                logger.error(f"Failed to schedule Telegram message: {e}")
                return None
        else:
            logger.warning(f"Notification skipped: No running event loop (State: {self.state})")
            return None

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

    def start_listener(self, orchestrator=None):
        """Starts the Telegram bot listener in a background thread with resilience."""
        if not self.token or self._is_permanently_disabled:
            return

        if self._thread and self._thread.is_alive():
            logger.info("Telegram listener is already running. Skipping start.")
            return

        def _run_bot_with_retry():
            # Initialize the authoritative event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

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
                    self.state = "RUNNING"

                    # run_polling is blocking. We use the loop we just created.
                    self._app.run_polling(close_loop=False)

                except (Forbidden, InvalidToken):
                    logger.critical("Telegram Listener: Token is unauthorized or invalid. Disabling Telegram permanently.")
                    self._is_permanently_disabled = True
                    self.state = "STOPPED"
                    break
                except telegram.error.Conflict:
                    self.state = "CONFLICT"
                    logger.warning("Telegram Listener: Conflict detected (another instance polling). Stopping polling to avoid API ban.")

                    # --- STRICT TEARDOWN SEQUENCE ---
                    if self._app and self._loop and self._loop.is_running():
                        try:
                            logger.info("Performing strict teardown of conflicting Telegram Application...")
                            asyncio.run_coroutine_threadsafe(self._app.stop(), self._loop).result(timeout=10)
                            asyncio.run_coroutine_threadsafe(self._app.shutdown(), self._loop).result(timeout=10)
                        except Exception as e:
                            logger.error(f"Conflict teardown failed: {e}")

                    # Inspect local project processes for duplicates
                    import psutil
                    import os
                    project_root = "C:\\Users\\Admin\\ai-strategy-lab"
                    duplicates = []
                    for proc in psutil.process_iter(['pid', 'cmdline']):
                        try:
                            cmd = " ".join(proc.info['cmdline'] or [])
                            if project_root in cmd and proc.pid != os.getpid():
                                duplicates.append(proc.pid)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    if duplicates:
                        logger.warning(f"Detected local duplicate project processes: {duplicates}. Attempting to terminate duplicates...")

                    # Bounded Exponential Backoff
                    if self._stop_event.wait(timeout=retry_delay):
                        break
                    retry_delay = min(retry_delay * 2, max_delay)
                    logger.info(f"Retrying Telegram polling in {retry_delay}s...")
                except (NetworkError, TimedOut) as e:
                    self.state = "RECONNECTING"
                    logger.warning(f"Telegram Listener: Transient network error ({e}). Retrying in {retry_delay}s...")

                    # Notify orchestrator of transport failure without rebuilding App
                    if orchestrator:
                        orchestrator._enter_outage("telegram", e)

                    if self._stop_event.wait(timeout=retry_delay):
                        break
                    retry_delay = min(retry_delay * 2, max_delay)
                except Exception as e:
                    self.state = "DEGRADED"
                    logger.error(f"Telegram Listener: Unexpected crash ({e}). Restarting in {retry_delay}s...")

                    # Fatal crash: notify orchestrator and trigger full rebuild in next iteration
                    if orchestrator:
                        orchestrator._enter_outage("telegram", e)

                    if self._stop_event.wait(timeout=retry_delay):
                        break
                    retry_delay = min(retry_delay * 2, max_delay)
                finally:
                    self._app = None

        self._thread = threading.Thread(target=_run_bot_with_retry, daemon=True)
        self._thread.start()

    def stop_listener(self):
        """Stops the Telegram bot listener gracefully."""
        logger.info("Stopping Telegram Listener...")
        self.state = "STOPPING"
        self._stop_event.set()

        if self._app and self._loop and self._loop.is_running():
            try:
                # Schedule async shutdown on the background loop
                asyncio.run_coroutine_threadsafe(self._app.stop(), self._loop)
                asyncio.run_coroutine_threadsafe(self._app.shutdown(), self._loop)
            except Exception as e:
                logger.error(f"Error scheduling Telegram app stop: {e}")

        if self._thread:
            self._thread.join(timeout=5)

        if self._loop:
            try:
                self._loop.close()
            except Exception as e:
                logger.error(f"Error closing event loop: {e}")

        self.state = "STOPPED"
