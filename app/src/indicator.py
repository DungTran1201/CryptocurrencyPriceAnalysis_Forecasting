import pandas as pd
import numpy as np
from abc import ABC, abstractmethod

from config import (
    OperationLogger, 
    ExceptionLogger, 
    PerformanceLogger)

op_log = OperationLogger("Indicator - OP")
ex_log = ExceptionLogger("Indicator - EX")
pref_log = PerformanceLogger("Indicator - PE")

class BaseIndicator(ABC):
    def __init__(self, **kwargs):
        self.params = kwargs

    def validate(self, df: pd.DataFrame):
        """Kiểm tra các ngoại lệ cơ bản trước khi tính toán."""
        # Kiểm tra DataFrame có rỗng không
        if df.empty:
            ex_log("EmptyDataFrame", "validate")
        
        # Kiểm tra cột 'Close' có tồn tại không
        if 'Close' not in df.columns:
            ex_log(f"ColumnsNotExsist: {'Close'}", "validate")
            
        # Kiểm tra độ dài window
        window = self.params.get('window')
        if window and len(df) < window:
            ex_log(f"IndexOutOfRange: df_lenght < {window}")

    @abstractmethod
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        pass

    # Wrapper để gọi validate tự động
    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate(df)
        return self.calculate(df)

# SMA Indicator 
class SMAIndicator(BaseIndicator):
    @pref_log.track
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        window = self.params.get('window', 14)
        df[f'SMA_{window}'] = df['Close'].rolling(window=window).mean()
        return df

# New: EMA Indicator
class EMAIndicator(BaseIndicator):
    """Calculates Exponential Moving Average."""
    @pref_log.track
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        window = self.params.get('window', 14)
        df[f'EMA_{window}'] = df['Close'].ewm(span=window, adjust=False).mean()
        return df

# New: Bollinger Bands Indicator
class BollingerBandsIndicator(BaseIndicator):
    """Calculates Bollinger Bands (Upper, Middle, Lower)."""
    @pref_log.track
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        window = self.params.get('window', 20)
        num_std = self.params.get('num_std', 2)
        
        # Calculate Middle Band (SMA)
        middle_band = df['Close'].rolling(window=window).mean()
        # Calculate Standard Deviation
        std = df['Close'].rolling(window=window).std()
        
        df[f'BB_Middle_{window}'] = middle_band
        df[f'BB_Upper_{window}'] = middle_band + (std * num_std)
        df[f'BB_Lower_{window}'] = middle_band - (std * num_std)
        return df