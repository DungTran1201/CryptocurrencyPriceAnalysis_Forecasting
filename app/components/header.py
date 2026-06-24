import streamlit as st


from .timeframe import tf_window
from .technical import ti_window

def render_header():
    """Tạo header điều khiển khung thời gian."""
    # Khởi tạo an toàn trong hàm 

    if "active_header_dialog" not in st.session_state:
        st.session_state.active_header_dialog = None

    if "active_indicator_dialog" not in st.session_state:
        st.session_state.active_indicator_dialog = None
    

    st.markdown("### 🛠 Công cụ điều khiển")
    
    col1, col2 = st.columns([3, 1])

    with col1:
        if st.button("Time Frame"): 
            st.session_state.active_header_dialog = "TF"
            st.rerun()

    with col2:
        if st.button("Technical Indicator"): 
            st.session_state.active_header_dialog = "TI"
            st.rerun()
    
    if st.session_state.active_header_dialog == "TF":
        tf_window()
    if st.session_state.active_header_dialog == "TI":
        ti_window()
    

    st.markdown('---')
