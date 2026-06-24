
import pandas as pd

from config import (
    OperationLogger, 
    ExceptionLogger, 
    PerformanceLogger)

from .indicator import IndicatorFactory

op_log = OperationLogger("Data_Processor - OP")
ex_log = ExceptionLogger("Data_Processor - EX")
pref_log = PerformanceLogger("Data_Processor - PE")

@pref_log.track
def resample_data(dataframe: pd.DataFrame, 
                  timeframe: str = "1min") -> pd.DataFrame: 
    """
    Xử lý resample sử dụng 'min' thay vì 'T' để tương thích với pandas mới nhất.
    """
    try:
        op_log.info("Dataframe resample timeframe")
        # Chuyển đổi sang datetime (nếu chưa phải)
        dataframe['Open_time'] = pd.to_datetime(dataframe ['Open_time'], unit='ms')
        dataframe.set_index('Open_time', inplace=True)
        
        # Thay thế ký tự 'm' trong timeframe thành 'min' để pandas hiểu
        # Ví dụ: '1m' -> '1min', '5m' -> '5min'
        
        # Định nghĩa các cột cần gộp
        agg_dict = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }
        
        # Thực hiện resample
        resampled_df = dataframe.resample(timeframe).agg(agg_dict).dropna()
        op_log.info("Resample successfully")
        return resampled_df.reset_index()
    
    except Exception as e:
        raise e 
    
def apply_indicators(df: pd.DataFrame, 
                     config: dict) -> pd.DataFrame:
    """Hàm xử lý toàn bộ danh sách chỉ báo."""
    for indicator_name, instances in config.items():
        if not instances: 
            continue
        else:
            for params in instances:
                try:
                    # 1. Khởi tạo
                    indicator = IndicatorFactory.get_indicator(indicator_name, params)
                    # 2. Tính toán và cập nhật DataFrame
                    df = indicator.run(df)
                    op_log.info(f"Computing {indicator_name} successfully!")
                except Exception as e:
                    ex_log.handle(f"Lỗi khi tính {indicator_name} (ID: {params.get('id')}): {e}")
    return df

        
    