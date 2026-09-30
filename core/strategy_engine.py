import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RegimeDetector:
    """
    Analyzes market regime to distinguish between trending and ranging markets.
    """
    def __init__(self, adx_threshold: float = 25.0, ranging_threshold: float = 20.0):
        self.adx_threshold = adx_threshold
        self.ranging_threshold = ranging_threshold

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        Calculates the Average Directional Index (ADX) to measure trend strength.
        """
        if len(df) < period * 2:
            return 0.0

        # Calculate True Range (TR)
        df = df.copy()
        df['h_l'] = df['high'] - df['low']
        df['h_pc'] = abs(df['high'] - df['close'].shift(1))
        df['l_pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h_l', 'h_pc', 'l_pc']].max(axis=1)

        # Calculate Directional Movement (+DM, -DM)
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']

        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)

        # Smooth TR, +DM, -DM
        tr_smooth = df['tr'].rolling(window=period).mean()
        plus_dm_smooth = df['plus_dm'].rolling(window=period).mean()
        minus_dm_smooth = df['minus_dm'].rolling(window=period).mean()

        # Calculate DI+ and DI-
        plus_di = 100 * (plus_dm_smooth / tr_smooth)
        minus_di = 100 * (minus_dm_smooth / tr_smooth)

        # Calculate DX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)

        # ADX is the SMA of DX
        adx = dx.rolling(window=period).mean()
        return float(adx.iloc[-1])

    def is_aligned(self, direction: str, mtf_data: Dict[str, pd.DataFrame]) -> Tuple[bool, str]:
        """
        Verifies if the signal direction matches the HTF trend (H4).
        Returns (is_aligned, status_message).
        """
        try:
            h4 = mtf_data.get('H4')
            if h4 is None or h4.empty:
                return True, "H4 data missing, skipping alignment check"

            current_price = h4['close'].iloc[-1]
            sma200 = h4['SMA_200'].iloc[-1] if 'SMA_200' in h4.columns else None

            if sma200 is None:
                return True, "SMA_200 missing on H4, skipping alignment check"

            if direction == "LONG" and current_price < sma200:
                return False, f"Regime Mismatch: Price ({current_price:.2f}) < SMA200 ({sma200:.2f}) on H4"
            if direction == "SHORT" and current_price > sma200:
                return False, f"Regime Mismatch: Price ({current_price:.2f}) > SMA200 ({sma200:.2f}) on H4"

            return True, "HTF Trend Aligned"
        except Exception as e:
            logger.error(f"Regime alignment error: {e}")
            return True, f"Alignment error: {e}"

class StrategyEngine:
    """
    The 'Sieve': Pass 1 of the hybrid backtester.
    Executes deterministic JSON-based rulesets against massive datasets to find
    Candidate Signals for the AI Reviewer.
    """
    def __init__(self):
        # Mapping of DSL trigger names to internal methods
        self.pattern_map = {
            "bullish_engulfing": self._is_bullish_engulfing,
            "bearish_engulfing": self._is_bearish_engulfing,
            "pin_bar": self._is_pin_bar,
            "inside_bar": self._is_inside_bar,
        }
        self.regime_detector = RegimeDetector()

    def find_candidates(self, strategy: Dict[str, Any], datalake: Any) -> List[Dict[str, Any]]:
        """
        Scans the data lake for candidate signals matching the strategy rules.
        """
        version = strategy.get('version', 'unknown')
        instrument = strategy.get('instrument', 'XAU_USD')
        granularity = strategy.get('granularity', 'H1')
        rules = strategy.get('rules', {})

        logger.info(f"Scanning {instrument} {granularity} for strategy {version}...")

        df = datalake.load_data(instrument, granularity)
        if df.empty:
            logger.warning("No data available to scan.")
            return []

        candidates = []

        # The DSL expects a 'trigger' (Price Action Pattern) and optional 'filters' (Indicators)
        trigger_name = rules.get('trigger', '').lower()
        filters = rules.get('filters', [])

        if trigger_name not in self.pattern_map:
            logger.error(f"Unsupported trigger: {trigger_name}")
            return []

        pattern_func = self.pattern_map[trigger_name]

        # Vectorized scanning is preferred, but for complex patterns we iterate or use rolling windows
        # To keep this performant, we use numpy arrays
        closes = df['close'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values

        for i in range(1, len(df)):
            # Check deterministic trigger
            if pattern_func(opens, closes, highs, lows, i):
                # Check filters (e.g., "RSI < 30")
                # Note: In a full implementation, indicators would be pre-calculated in datalake
                if self._check_filters(df, i, filters):
                    candidates.append({
                        'timestamp': df.index[i],
                        'instrument': instrument,
                        'granularity': granularity,
                        'trigger': trigger_name,
                        'price': closes[i],
                        'context_window': i # Store index for AI Reviewer to slice the DF
                    })

        logger.info(f"Sieve completed. Found {len(candidates)} candidates.")
        return candidates

    def _check_filters(self, df: pd.DataFrame, index: int, filters: List[Dict]) -> bool:
        """
        Validates candidate signals against secondary filters (e.g., Trend, Volume, RSI).
        """
        for f in filters:
            indicator = f.get('indicator')
            op = f.get('operator')
            val = f.get('value')

            # Implementation assumes indicators are columns in the dataframe
            if indicator in df.columns:
                current_val = df[indicator].iloc[index]
                if op == '<' and not (current_val < val): return False
                if op == '>' and not (current_val > val): return False
                if op == '==' and not (current_val == val): return False
            else:
                # For now, if indicator isn't pre-calculated, we skip it or log a warning
                pass
        return True

    def evaluate_confluence(self, mtf_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Analyzes multiple timeframes to return a summarized 'Confluence Score'.
        HTF (4H, 1H) -> Mid (30M, 15M) -> LTF (5M, 1M).
        """
        results = {
            'trend_alignment': False,
            'precision_entry': 'Low',
            'regime_filter_passed': True,
            'regime_status': 'Unknown',
            'details': {}
        }

        # 1. Regime Filter (ADX and Alignment)
        # We use H1 for the base ADX check as it balances noise and trend
        if 'H1' in mtf_data:
            h1_df = mtf_data['H1']
            adx = self.regime_detector.calculate_adx(h1_df)

            # Determine basic regime
            if adx < self.regime_detector.ranging_threshold:
                results['regime_filter_passed'] = False
                results['regime_status'] = f"Ranging Market (ADX: {adx:.2f})"
            elif adx > self.regime_detector.adx_threshold:
                results['regime_status'] = f"Strong Trend (ADX: {adx:.2f})"
            else:
                results['regime_status'] = f"Weak Trend (ADX: {adx:.2f})"

        # 2. HTF Trend Alignment (4H and 1H)
        htf_trends = []
        for gran in ['4H', '1H']:
            if gran in mtf_data:
                df = mtf_data[gran]
                if not df.empty:
                    # Using SMA 200 as a proxy for trend
                    last_close = df['close'].iloc[-1]
                    sma_200 = df['SMA_200'].iloc[-1] if 'SMA_200' in df.columns else 0
                    htf_trends.append('bullish' if last_close > sma_200 else 'bearish')

        if len(htf_trends) >= 2 and htf_trends[0] == htf_trends[1]:
            results['trend_alignment'] = True
            results['details']['htf_trend'] = htf_trends[0]
        elif len(htf_trends) >= 1:
            results['details']['htf_trend'] = htf_trends[0]

        # 3. LTF Precision (5M, 1M)
        ltf_precision = 'Low'
        for gran in ['5M', '1M']:
            if gran in mtf_data:
                df = mtf_data[gran]
                if not df.empty:
                    c = df['close'].values
                    o = df['open'].values
                    h = df['high'].values
                    l = df['low'].values
                    if self._is_pin_bar(o, c, h, l, len(df)-1):
                        ltf_precision = 'High'
                        break

        results['precision_entry'] = ltf_precision
        return results

    def _is_bullish_engulfing(self, o, c, h, l, i) -> bool:
        """
        Bullish Engulfing:
        1. Previous candle is bearish.
        2. Current candle is bullish.
        3. Current body engulfs previous body.
        """
        prev_bearish = c[i-1] < o[i-1]
        curr_bullish = c[i] > o[i]
        engulfs = (c[i] >= o[i-1]) and (o[i] <= c[i-1])
        return prev_bearish and curr_bullish and engulfs

    def _is_bearish_engulfing(self, o, c, h, l, i) -> bool:
        """Bearish Engulfing logic."""
        prev_bullish = c[i-1] > o[i-1]
        curr_bearish = c[i] < o[i]
        engulfs = (c[i] <= o[i-1]) and (o[i] >= c[i-1])
        return prev_bullish and curr_bearish and engulfs

    def _is_pin_bar(self, o, c, h, l, i) -> bool:
        """
        Pin Bar: Long wick, small body.
        Body size < 30% of total range.
        """
        body = abs(c[i] - o[i])
        total_range = h[i] - l[i]
        if total_range == 0: return False
        return (body / total_range) < 0.3

    def _is_inside_bar(self, o, c, h, l, i) -> bool:
        """Inside Bar: Current candle is completely within previous candle's range."""
        return (h[i] <= h[i-1]) and (l[i] >= l[i-1])
