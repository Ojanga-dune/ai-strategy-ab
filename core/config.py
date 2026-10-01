import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def get_project_root():
    """Returns the absolute path to the project root directory."""
    # This file is in core/config.py
    return Path(__file__).parent.parent

def load_config():
    """
    Centralized configuration loader.
    Returns a dictionary of validated settings.
    """
    root = get_project_root()
    env_path = root / ".env"
    
    # Load .env from absolute path
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=str(env_path))
    
    # Explicit Boolean Logic for Trading Mode
    live_trading_raw = os.getenv("LIVE_TRADING", "false").strip().lower()
    live_trading = live_trading_raw == "true"
    simulation_mode = not live_trading
    
    config = {
        "api_key": os.getenv("OANDA_API_KEY"),
        "account_id": os.getenv("OANDA_ACCOUNT_ID"),
        "telegram_token": os.getenv("TELEGRAM_API_KEY"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "live_trading": live_trading,
        "simulation_mode": simulation_mode,
        "oanda_env": "practice" if not live_trading else "live",
        "project_root": root,
        "data_dir": root / "data"
    }
    
    # Logging resulting mode (WITHOUT SECRETS)
    logger.info(f"Configuration Loaded - OANDA Environment: {config['oanda_env']}")
    logger.info(f"Configuration Loaded - Simulation Mode: {config['simulation_mode']}")
    
    return config

# Singleton instance for the session
settings = load_config()
