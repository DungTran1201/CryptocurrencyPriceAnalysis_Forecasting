
import pandas as pd
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
        self.column = kwargs.get('column', 'Close')

    def validate(self, df: pd.DataFrame):
        """Kiểm tra các ngoại lệ cơ bản trước khi tính toán."""
        # Kiểm tra DataFrame có rỗng không
        if df.empty:
            ex_log("EmptyDataFrame", "validate")
            
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
        df[f'SMA_{window}'] = df[self.column].rolling(window=window).mean()
        return df

# New: EMA Indicator
class EMAIndicator(BaseIndicator):
    """Calculates Exponential Moving Average."""
    @pref_log.track
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        window = self.params.get('window', 14)
        df[f'EMA_{window}'] = df[self.column].ewm(span=window, adjust=False).mean()
        return df

# New: Bollinger Bands Indicator
class BollingerBandsIndicator(BaseIndicator):
    """Calculates Bollinger Bands (Upper, Middle, Lower)."""
    @pref_log.track
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        window = self.params.get('window', 20)
        num_std = self.params.get('num_std', 2)
        
        # Calculate Middle Band (SMA)
        middle_band = df[self.column].rolling(window=window).mean()
        # Calculate Standard Deviation
        std = df[self.column].rolling(window=window).std()
        
        df[f'BB_Middle_{window}'] = middle_band
        df[f'BB_Upper_{window}'] = middle_band + (std * num_std)
        df[f'BB_Lower_{window}'] = middle_band - (std * num_std)
        return df


class RSIIndicator(BaseIndicator):
    """Calculates Relative Strength Index (RSI)."""
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        window = self.params.get('window', 14)
        delta = df[self.column].diff()
        
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        
        rs = gain / loss
        df[f'RSI_{window}'] = 100 - (100 / (1 + rs))
        return df


# Trong data_processor.py

class IndicatorFactory:
    _mapping = {
        'SMA': SMAIndicator,
        'EMA': EMAIndicator,
        'RSI': RSIIndicator,
        'BOLL': BollingerBandsIndicator
    }

    @classmethod
    def get_indicator(cls, name, params):
        indicator_class = cls._mapping.get(name)
        if not indicator_class:
            ex_log.handle(f"Indicator not init: {indicator_class}")
        # Truyền tất cả cấu hình (trừ 'id' và 'color') vào lớp con
        clean_params = {k: v for k, v in params.items() if k not in ['id', 'color']}
        return indicator_class(**clean_params)
