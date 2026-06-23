import os
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from src.data_processor import resample_data # Ensure this module handles resample logic
from components.header import render_header
from config import OperationLogger, ExceptionLogger, PerformanceLogger, setup

# Initialize Loggers
op_log = OperationLogger("Dashboard - OP")
ex_log = ExceptionLogger("Dashboard - EX")
perf_log = PerformanceLogger("Dashboard - PE")

# Define Data Path
BASE_DIR = setup.base_dir
FILE_NAME = f'{setup.data.symbol}_{setup.data.time.frame}_data.csv'
DATA_PATH = os.path.join(BASE_DIR, "data", "raw", FILE_NAME)

# df = pd.read_csv(DATA_PATH)

def plot_chart(df: pd.DataFrame, timeframe: str) -> None:
    """Render interactive candlestick chart."""
    if df.empty:
        st.warning("No data available for this timeframe.")
        return

    st.subheader(f"Price Chart ({timeframe})")
    
    fig = go.Figure(data=[go.Candlestick(
        x=df['Open_time'],
        open=df['Open'],
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350'
    )])
    
    fig.update_layout(
        template='plotly_dark',
        xaxis_rangeslider_visible=False,
        height=500,
        margin=dict(l=0, r=0, t=30, b=0)
    )
    
    st.plotly_chart(fig, use_container_width=True)

def main():
    st.set_page_config(layout="wide", page_title="Binance Style Dashboard")

    # 1. Render Header and get current timeframe selection
    # Assuming render_header returns the selected timeframe
    selected_tf = render_header()
    op_log.info(f"TimeFrame: {selected_tf}")
    df = pd.read_csv(DATA_PATH)
    
    # 2. Load and Resample Data (Streamlit will re-run this when selected_tf changes)
    df_resample = resample_data(df, selected_tf)
    
    # 3. Plot Chart
    plot_chart(df_resample, selected_tf)
    
    if not df.empty:
        st.write("Detailed Data:", df_resample)

if __name__ == "__main__":
    main()