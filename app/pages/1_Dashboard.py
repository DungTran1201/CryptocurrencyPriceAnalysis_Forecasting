import os
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from plotly.subplots import make_subplots
from src import resample_data, apply_indicators  # Ensure this module handles resample logic
from components.header import render_header
from config import (
    OperationLogger, 
    ExceptionLogger, 
    PerformanceLogger, 
    setup)

# Initialize Loggers
op_log = OperationLogger("Dashboard - OP")
ex_log = ExceptionLogger("Dashboard - EX")
perf_log = PerformanceLogger("Dashboard - PE")

# Define Data Path
BASE_DIR = setup.base_dir
FILE_NAME = f'{setup.data.symbol}_{setup.data.time.frame}_data.csv'
DATA_PATH = os.path.join(BASE_DIR, "data", "raw", FILE_NAME)

df = pd.read_csv(DATA_PATH)
indicators_name = ["SMA", "EMA", "BOLL", "RSI"]

def plot_chart(df: pd.DataFrame, timeframe: str, config: dict) -> None:
    """
    Vẽ biểu đồ nến và tự động vẽ các chỉ báo từ file cấu hình.
    """
    if df.empty:
        st.warning("Không có dữ liệu để hiển thị.")
        return

    st.subheader(f"Biểu đồ kỹ thuật ({timeframe})")

    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=(f"Price Chart ({timeframe})", "Volume", "RSI")
    )
    
    # fig = go.Figure

    # 1. Vẽ biểu đồ nến gốc
    fig.add_trace(go.Candlestick(
        x=df['Open_time'], open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name='Market Data',
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ),row=1, col=1)

    # 2. Tự động lặp qua cấu hình để vẽ các chỉ báo
    # Ví dụ config: {'SMA': [...], 'EMA': [...], ...}
    for indicator_type, indicator_list in config.items():
        for item in indicator_list:
            # Tạo tên cột dựa trên quy tắc bạn đã đặt (ví dụ: SMA_Close_14)
            col_name = f"{indicator_type}_{item['window']}"
            if "BB" not in col_name:  
                if col_name in df.columns:
                    fig.add_trace(go.Scatter(
                        x=df['Open_time'],
                        y=df[col_name],
                        mode='lines',
                        name=f"{indicator_type} ({item['window']})",
                        line=dict(color=item['color'], width=1.5)
                    ), row=1, col=1)
            else:
                for band in ['Upper', 'Middle', 'Lower']:
                    col = f"BB_{band}_{item['window']}"
                    if col in df.columns:
                        fig.add_trace(go.Scatter(x=df['Open_time'], 
                                                y=df[col], name=f"BOLL {band}", 
                                                line=dict(width=1)), row=1, col=1)
                            
    fig.add_trace(go.Bar(
        x=df['Open_time'], y=df['Volume'], name='Volume',
        marker_color=['#26a69a' if row['Close'] >= row['Open'] else '#ef5350' for _, row in df.iterrows()]
    ), row=2, col=1)

    # 3. Vẽ RSI (Hàng 3)
    if 'RSI' in config:
        for item in config['RSI']:
            col = f"RSI_{item['column']}_{item['window']}"
            if col in df.columns:
                fig.add_trace(go.Scatter(x=df['Open_time'], y=df[col], name='RSI', line=dict(color='#FFD700')), row=3, col=1)
                # Thêm đường kẻ tham chiếu 30/70
                fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    fig.update_layout(
        template='plotly_dark',
        xaxis_rangeslider_visible=False,
        height=600,
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    st.plotly_chart(fig, use_container_width=True)



def main():
    st.set_page_config(layout="wide", page_title="Binance Style Dashboard")

    if "data" not in st.session_state: 
        st.session_state.data = df
    if "data_copy" not in st.session_state: 
        st.session_state.data_copy = df.copy()
    
    if "tf_select" not in st.session_state:
        st.session_state.tf_select = "1min"

    if "indicators_name" not in st.session_state:
        st.session_state.indicators_name = indicators_name
    
    if "ti_select" not in st.session_state: 
        st.session_state.ti_select = dict.fromkeys(st.session_state.indicators_name, [])
    

    # 1. Render Header and get current timeframe selection
    # Assuming render_header returns the selected timeframe
    render_header()
    op_log.info(f"TimeFrame: {st.session_state.tf_select}")
    
    # 2. Load and Resample Data (Streamlit will re-run this when selected_tf changes)
    st.session_state.data_copy = resample_data(st.session_state.data_copy, 
                                               st.session_state.tf_select)
    st.session_state.data_copy = apply_indicators(st.session_state.data_copy, 
                                                  st.session_state.ti_select)
    
    op_log.info(f"Technical Indicator: {st.session_state.ti_select}")
    
    # 3. Plot Chart
    plot_chart(st.session_state.data_copy, 
               st.session_state.tf_select, 
               st.session_state.ti_select)

    
    if not df.empty:
        st.write("Detailed Data:", st.session_state.data_copy)
    

if __name__ == "__main__":
    main()













# from plotly.subplots import make_subplots

# def plot_chart(df: pd.DataFrame, timeframe: str, config: dict) -> None:
#     """
#     Vẽ biểu đồ nến, Volume ở dưới và RSI ở khung phụ.
#     """
#     if df.empty:
#         st.warning("Không có dữ liệu.")
#         return

#     # Tạo subplots: Hàng 1 (Giá - 60%), Hàng 2 (Volume - 20%), Hàng 3 (RSI - 20%)
#     fig = make_subplots(
#         rows=3, cols=1, 
#         shared_xaxes=True,
#         vertical_spacing=0.05,
#         row_heights=[0.6, 0.2, 0.2],
#         subplot_titles=(f"Price Chart ({timeframe})", "Volume", "RSI")
#     )

#     # 1. Vẽ Candlestick (Hàng 1)
#     fig.add_trace(go.Candlestick(
#         x=df['Open_time'], open=df['Open'], high=df['High'],
#         low=df['Low'], close=df['Close'], name='Market Data'
#     ), row=1, col=1)

#     # Vẽ các chỉ báo overlay (SMA, EMA, Bollinger) lên hàng 1
#     for indicator_type, indicator_list in config.items():
#         if indicator_type in ['SMA', 'EMA', 'BOLL']:
#             for item in indicator_list:
#                 if indicator_type == 'BOLL':
#                     for band in ['Upper', 'Middle', 'Lower']:
#                         col = f"BOLL_{band}_{item['window']}"
#                         if col in df.columns:
#                             fig.add_trace(go.Scatter(x=df['Open_time'], y=df[col], name=f"BOLL {band}", line=dict(width=1)), row=1, col=1)
#                 else:
#                     col = f"{indicator_type}_{item['column']}_{item['window']}"
#                     if col in df.columns:
#                         fig.add_trace(go.Scatter(x=df['Open_time'], y=df[col], name=f"{indicator_type} {item['window']}"), row=1, col=1)

#     # 2. Vẽ Volume (Hàng 2)
#     fig.add_trace(go.Bar(
#         x=df['Open_time'], y=df['Volume'], name='Volume',
#         marker_color=['#26a69a' if row['Close'] >= row['Open'] else '#ef5350' for _, row in df.iterrows()]
#     ), row=2, col=1)

#     # 3. Vẽ RSI (Hàng 3)
#     if 'RSI' in config:
#         for item in config['RSI']:
#             col = f"RSI_{item['column']}_{item['window']}"
#             if col in df.columns:
#                 fig.add_trace(go.Scatter(x=df['Open_time'], y=df[col], name='RSI', line=dict(color='#FFD700')), row=3, col=1)
#                 # Thêm đường kẻ tham chiếu 30/70
#                 fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
#                 fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

#     # Định dạng layout
#     fig.update_layout(
#         template='plotly_dark',
#         xaxis_rangeslider_visible=False,
#         height=800,
#         showlegend=True
#     )
    
#     st.plotly_chart(fig, use_container_width=True)