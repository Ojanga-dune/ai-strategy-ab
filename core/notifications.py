import logging
import asyncio
import threading
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)

class NotificationManager:
    """
    Handles outgoing alerts and incoming commands from Telegram.
    """
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token
        self.chat_id = chat_id
        self.bot = Bot(token=token) if token else None

        # Storage for command callbacks to be set by the orchestrator (live_main.py)
        self.callbacks: Dict[str, Callable] = {}
        self._app = None
        self._thread = None

        if not token or not chat_id:
            logger.warning("Telegram credentials missing. Notifications and Command Control are disabled.")

    async def send_message(self, text: str):
        """Sends a message to the configured Telegram chat."""
        if not self.bot or not self.chat_id:
            logger.info(f"[NOTIFICATION-DISABLED] {text}")
            return

        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    def send_sync(self, text: str):
        """Synchronous wrapper for sending messages."""
        if not self.bot or not self.chat_id:
            logger.info(f"[NOTIFICATION-DISABLED] {text}")
            return

        def _send():
            try:
                asyncio.run(self.send_message(text))
            except Exception as e:
                logger.error(f"Async send failed: {e}")

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
        # Handle /commands
        if text.startswith('/'):
            # Clean the command: remove '/', split and take the first part
            cmd_part = text.split()[0]
            cmd = cmd_part[1:].lower().strip()

            if cmd in self.callbacks:
                try:
                    # Call the registered callback with the full text and the context
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
            # Handle plain text messages (for Portfolio Manager consultations)
            if 'message' in self.callbacks:
                response = self.callbacks['message'](text, context)
                if response:
                    await self.send_message(response)

    def start_listener(self):
        """Starts the Telegram bot listener in a background thread."""
        if not self.token:
            return

        def _run_bot():
            try:
                # Create the Application
                self._app = ApplicationBuilder().token(self.token).build()

                # Register a general message handler that routes to our callbacks
                self._app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_message))
                self._app.add_handler(MessageHandler(filters.COMMAND, self._handle_message))

                logger.info("Telegram Command Listener started...")
                self._app.run_polling()
            except Exception as e:
                logger.error(f"Telegram Listener crashed: {e}")

        self._thread = threading.Thread(target=_run_bot, daemon=True)
        self._thread.start()

    def stop_listener(self):
        """Stops the Telegram bot listener."""
        if self._app:
            # Note: Application.stop() is async, this is a simplified stop
            # In a full implementation, we'd handle the event loop properly
            logger.info("Stopping Telegram Listener...")
