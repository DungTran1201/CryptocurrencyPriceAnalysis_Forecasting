import pandas as pd

def resample_data(file_path, timeframe):
    """
    Xử lý resample sử dụng 'min' thay vì 'T' để tương thích với pandas mới nhất.
    """
    try:
        df = pd.read_csv(file_path)
        # Chuyển đổi sang datetime (nếu chưa phải)
        df['Open_time'] = pd.to_datetime(df['Open_time'], unit='ms')
        df.set_index('Open_time', inplace=True)
        
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
        resampled_df = df.resample(timeframe).agg(agg_dict).dropna()
        
        return resampled_df.reset_index()
    except Exception as e:
        raise ValueError(f"Lỗi khi xử lý: {e}")