import sys

file_path = 'live_main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Search for the start of the main try block
start_marker = '    try:\n        # Load environment variables explicitly'
end_marker = '        circuit_breaker = CircuitBreaker(threshold=5)'

start_idx = content.find(start_marker)
if start_idx == -1:
    print("Start marker not found")
    sys.exit(1)

end_idx = content.find(end_marker) + len(end_marker)
if end_idx == -1:
    print("End marker not found")
    sys.exit(1)

replacement = """    try:
        # Configuration is now handled by core.config.settings singleton
        api_key = settings.api_key
        account_id = settings.account_id

        if not api_key or not account_id:
            logger.error("Missing OANDA_API_KEY or OANDA_ACCOUNT_ID in environment variables.")
            return

        # --- Initialization ---
        logger.info("Initializing Autonomous Live Bot...")
        
        # Use absolute path for data directory from settings
        data_dir = settings.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        
        dl = DataLake(api_key=api_key, account_id=account_id)
        engine = StrategyEngine()
        reviewer = AIReviewer()
        risk_manager = RiskManager(risk_per_trade=0.01)
        tracker = TradeTracker()
        state_manager = StateManager()
        evolver = PostMortemAgent()
        news_guard = NewsGuard()
        signal_tracker = SignalTracker()
        circuit_breaker = CircuitBreaker(threshold=5)"""

new_content = content[:start_idx] + replacement + content[end_idx:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Successfully updated live_main.py")
