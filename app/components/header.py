import streamlit as st

if "tf_sellect" not in st.session_state:
    st.session_state.tf_sellect = "1min"

@st.dialog("TimeFrame")
def tf_window():
    col1, col2 = st.columns([3, 1])
    with col1: 
        timeframes = ['5min', '15min', '30min', '1h', '4h', '1d']
        selected_tf = st.radio("Chọn Timeframe:", timeframes, horizontal=True)
    with col2: 
        custom_tf = st.text_input("Custom (vd: 2H, 3D):", placeholder="Nhập nhanh...")

    if st.button("Đóng"):
        st.session_state.tf_sellect = selected_tf if selected_tf else custom_tf
        st.rerun()

def render_header():
    """Tạo header điều khiển khung thời gian."""
    st.markdown("### 🛠 Công cụ điều khiển")
    
    if st.button("Time Frame"): 
        tf_window()
    st.markdown('---')

    return st.session_state.tf_sellect 

