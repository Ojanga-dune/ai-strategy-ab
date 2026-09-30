import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Analytics:
    """
    The 'Scorecard': Quantifies the performance of verified trades.
    Calculates institutional-grade metrics to determine if a strategy is viable.
    """
    def __init__(self):
        pass

    def calculate_performance(self, trades: List[Dict[str, Any]], datalake: Any = None, current_price: float = None) -> Dict[str, Any]:
        """
        Processes a list of verified trades and returns a performance report.
        Strictly excludes estimated PnL to ensure institutional-grade metrics.
        """
        if not trades:
            return {"status": "No trades to analyze"}

        # Filter for closed trades and exclude any that were purely estimated
        closed_trades = [t for t in trades if t.get('status') == 'CLOSED' and t.get('pnl_source') == 'oanda']
        if not closed_trades:
            return {"status": "No verified closed trades to analyze"}

        results = []
        for t in closed_trades:
            pnl = t.get('pnl')
            if pnl is None:
                continue

            try:
                pnl_val = float(pnl)
            except (ValueError, TypeError):
                logger.warning(f"Invalid PnL value {pnl} for trade {t.get('trade_id')}. Skipping.")
                continue

            results.append({
                'timestamp': t.get('timestamp'),
                'pnl': pnl_val,
                'win': pnl_val > 0
            })

        if not results:
            return {"status": "No valid PnL data found"}

        df = pd.DataFrame(results)



        df = pd.DataFrame(results)

        # Basic Metrics
        total_trades = len(df)
        wins = df[df['win'] == True].shape[0]
        losses = total_trades - wins
        win_rate = wins / total_trades if total_trades > 0 else 0

        # Profit Factor = (Sum of Gains) / (Sum of Losses)
        gains = df[df['pnl'] > 0]['pnl'].sum()
        losses_val = abs(df[df['pnl'] < 0]['pnl'].sum())
        profit_factor = gains / losses_val if losses_val != 0 else float('inf')

        # Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
        avg_win = df[df['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
        avg_loss = abs(df[df['pnl'] < 0]['pnl'].mean()) if losses > 0 else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Max Drawdown (Simulated from cumulative PnL)
        df['cum_pnl'] = df['pnl'].cumsum()
        peak = df['cum_pnl'].expanding().max()
        drawdown = peak - df['cum_pnl']
        max_dd = drawdown.max()

        metrics = {
            "total_trades": total_trades,
            "win_rate": f"{win_rate:.2%}",
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "max_drawdown": round(max_dd, 2),
            "total_pnl": round(df['pnl'].sum(), 2),
            "verdict": "VIABLE" if profit_factor > 1.2 and expectancy > 0 else "UNVIABLE"
        }

        logger.info(f"Analytics Result: {metrics['verdict']} (PF: {metrics['profit_factor']})")
        return metrics

    def generate_critique_report(self, trades: List[Dict[str, Any]], metrics: Dict[str, Any]) -> str:
        """
        Generates a natural language report for the AI Architect to use in optimization.
        """
        win_trades = [t for t in trades if t.get('win', False)]
        loss_trades = [t for t in trades if not t.get('win', False)]

        report = f"STRATEGY PERFORMANCE REPORT\n"
        report += f"Verdict: {metrics['verdict']}\n"
        report += f"Profit Factor: {metrics['profit_factor']} | Win Rate: {metrics['win_rate']}\n"
        report += f"Expectancy: {metrics['expectancy']}\n\n"

        report += "FAILURE ANALYSIS:\n"
        if loss_trades:
            # Sample a few losses to show the AI what went wrong
            sample_loss = loss_trades[0]
            report += f"Example Failure: {sample_loss['timestamp']} - Reasoning: {sample_loss.get('ai_reasoning', 'N/A')}\n"
        else:
            report += "No losses recorded.\n"

        return report
