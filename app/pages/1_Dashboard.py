import os
import time

from pathlib import Path
from config import (
    OperationLogger, 
    ExceptionLogger, 
    PerformanceLogger, 
    setup)



import pandas as pd
from src.data_processor import resample_data

import streamlit as st
import plotly.graph_objects as go

from components.header import render_header

op_log = OperationLogger("DashBroad - OP")
ex_log = ExceptionLogger("DashBroad - EX")
perf_log = PerformanceLogger("DashBroad - PE")


BASE_DIR = setup.base_dir
FILE_NAME = f'{setup.data.symbol}_{setup.data.time.frame}_data.csv'
DATA_PATH = str(os.path.join(BASE_DIR, "data", "raw", FILE_NAME) )

@perf_log.track
def df_loader(file_path: str) -> pd.DataFrame : 
    
    try: 
        op_log.info("DashBroad: Load dataframe")
        data = pd.read_csv(DATA_PATH) 
        return data 
    except FileNotFoundError as e: 
        ex_log.handle(e, "df_loader")
        return 


@perf_log.track
def plot_chart(df: pd.DataFrame) -> None:
    try:
        op_log.info('Chart: PLot cadinates ')
        resample_df = resample_data(df, tf)
            
            # 3. Vẽ biểu đồ nến
        st.subheader(f"Biểu đồ giá ({tf})")
        fig = go.Figure(data=[go.Candlestick(
                x=resample_df['Open_time'], 
                open=resample_df['Open'], 
                high=resample_df['High'],
                low=resample_df['Low'], 
                close=resample_df['Close'],
                increasing_line_color='#26a69a', 
                decreasing_line_color='#ef5350'
            )])
            
        fig.update_layout(template='plotly_dark', 
                            xaxis_rangeslider_visible=False, 
                            height=500)
            
        st.plotly_chart(fig, use_container_width=True)
        st.write("Dữ liệu chi tiết:", resample_df)
            
    except Exception as e:
        ex_log.handle(e, 'plot_chart')


if __name__ == "__main__": 
    st.set_page_config(layout="wide", 
                   page_title="Binance Style Dashboard")
    # 1. Header
    tf = render_header()
    df = df_loader(file_path = DATA_PATH)
    plot_chart(df = df)
     