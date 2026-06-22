import streamlit as st
import plotly.graph_objects as go
from src.data_processor import resample_data
from components.header import render_header
import os

st.set_page_config(layout="wide", page_title="Binance Style Dashboard")

# 1. Header
tf = render_header()

# 2. Logic chính
data_file = "/workspaces/Binance-Predict-Value-And-Trend/data/raw/BTCUSDT_1m_data.csv"

if not os.path.exists(data_file):
    st.error(f"Không tìm thấy file dữ liệu tại {data_file}")
else:
    try:
        # Xử lý dữ liệu
        df = resample_data(data_file, tf)
        
        # 3. Vẽ biểu đồ nến
        st.subheader(f"Biểu đồ giá ({tf})")
        fig = go.Figure(data=[go.Candlestick(
            x=df['Open_time'], open=df['Open'], high=df['High'],
            low=df['Low'], close=df['Close'],
            increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
        )])
        
        fig.update_layout(template='plotly_dark', xaxis_rangeslider_visible=False, height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        # Hiển thị bảng dữ liệu
        st.write("Dữ liệu chi tiết:", df)
        
    except Exception as e:
        st.error(f"⚠️ Lỗi hệ thống: {e}")