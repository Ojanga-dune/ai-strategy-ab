import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DataLake:
    """
    Handles historical data ingestion from OANDA and persistence in Parquet format.
    Structure: data/lake/{instrument}/{granularity}.parquet
    """
    def __init__(self, base_path="data/lake", api_key=None, account_id=None):
        self.base_path = Path(base_path)
        self.api_key = api_key
        self.account_id = account_id
        self.base_path.mkdir(parents=True, exist_ok=True)

        if api_key:
            self.client = API(access_token=api_key)
        else:
            self.client = None
            logger.warning("OANDA API key not provided. DataLake will operate in read-only mode for existing files.")

    def get_file_path(self, instrument: str, granularity: str) -> Path:
        """Returns the path to the parquet file for a given instrument and granularity."""
        return self.base_path / instrument.upper() / f"{granularity}.parquet"

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates the necessary technical indicators for the StrategyEngine.
        Implemented manually to avoid dependency conflicts with Python 3.14.
        """
        df = df.copy()

        # 1. Relative Strength Index (RSI) - 14 Period
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # 2. Simple Moving Average (SMA) - 200 Period
        df['SMA_200'] = df['close'].rolling(window=200).mean()

        # 3. Average True Range (ATR) - 14 Period
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(window=14).mean()

        return df

    def download_historical_data(self, instrument: str, granularity: str, count: int = 5000, from_time: str = None):
        """
        Downloads historical candles from OANDA and saves them to Parquet.
        """
        if not self.client:
            raise ConnectionError("OANDA API client not initialized. Please provide an API key.")

        logger.info(f"Downloading {count} candles for {instrument} ({granularity})...")

        params = {
            "instrument": instrument.upper(),
            "granularity": granularity,
            "count": count,
        }
        if from_time:
            params["from"] = from_time

        r = instruments.InstrumentsCandles(params=params)
        self.client.request(r)

        candles = r.response.get('candles', [])

        data = []
        for c in candles:
            if c.get('complete'):
                data.append({
                    'time': c['time'],
                    'open': float(c['mid']['o']),
                    'high': float(c['mid']['h']),
                    'low': float(c['mid']['l']),
                    'close': float(c['mid']['c']),
                    'volume': int(c['volume'])
                })

        df = pd.DataFrame(data)
        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)

        # CALCULATE INDICATORS BEFORE SAVING
        df = self._calculate_indicators(df)

        file_path = self.get_file_path(instrument, granularity)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_parquet(file_path, engine='pyarrow', compression='snappy')
        logger.info(f"Saved {len(df)} candles (with indicators) to {file_path}")
        return df

    def load_data(self, instrument: str, granularity: str) -> pd.DataFrame:
        """Loads historical data from the Parquet lake."""
        file_path = self.get_file_path(instrument, granularity)
        if not file_path.exists():
            logger.error(f"No data found at {file_path}. Please download data first.")
            return pd.DataFrame()

        logger.info(f"Loading {instrument} {granularity} data from lake...")
        df = pd.read_parquet(file_path)

        # Ensure indicators exist (in case file was saved before indicators were added)
        if 'RSI' not in df.columns:
            df = self._calculate_indicators(df)

        return df

    def update_lake(self, instrument: str, granularity: str, days=1):
        """Appends latest data to the existing parquet file."""
        df_existing = self.load_data(instrument, granularity)
        df_new = self.download_historical_data(instrument, granularity, count=1000)

        df_combined = pd.concat([df_existing, df_new])
        df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
        df_combined.sort_index(inplace=True)

        # Re-calculate indicators on the combined set to avoid gaps at the merge point
        df_combined = self._calculate_indicators(df_combined)

        file_path = self.get_file_path(instrument, granularity)
        df_combined.to_parquet(file_path, engine='pyarrow', compression='snappy')
        logger.info(f"Updated {instrument} {granularity} lake.")
        return df_combined

    def get_confluence_data(self, instrument: str, mtf_dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Aggregates indicators across multiple timeframes to determine market confluence.
        """
        confluence = {}
        for gran, df in mtf_dfs.items():
            # Ensure indicators are calculated for this timeframe
            df = self._calculate_indicators(df)

            # Extract most recent key values
            if df.empty:
                continue

            last_row = df.iloc[-1]
            confluence[gran] = {
                'close': last_row['close'],
                'rsi': last_row.get('RSI'),
                'sma_200': last_row.get('SMA_200'),
                'atr': last_row.get('ATR'),
                'trend': 'bullish' if last_row['close'] > last_row.get('SMA_200', 0) else 'bearish'
            }

        return confluence
