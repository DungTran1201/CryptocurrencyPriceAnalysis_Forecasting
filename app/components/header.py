import streamlit as st



@st.dialog("TimeFrame")
def tf_window():
    col1, col2 = st.columns([3, 1])
    with col1: 
        timeframes = ['5min', '15min', '30min', '1h', '4h', '1d']
        selected_tf = st.radio("Select Timeframe:", timeframes, horizontal=True)
    with col2: 
        custom_tf = st.text_input("Custom (vd: 2H, 3D):", placeholder="Enter...")    

    if st.button("Đóng"):
        # Cập nhật giá trị vào session_state
        st.session_state.tf_sellect = custom_tf if custom_tf else selected_tf
        # Đóng dialog bằng cách tắt biến điều khiển
        st.session_state.show_tf_dialog = False
        st.rerun()

def render_header():
    """Tạo header điều khiển khung thời gian."""
    # Khởi tạo an toàn trong hàm 
    if "tf_sellect" not in st.session_state:
        st.session_state.tf_sellect = "1min"
    if "show_tf_dialog" not in st.session_state:
        st.session_state.show_tf_dialog = False

    st.markdown("### 🛠 Công cụ điều khiển")
    
    col1, col2 = st.columns([3, 1])

    with col1:
        if st.button("Time Frame"): 
            st.session_state.show_tf_dialog = True
            st.rerun()
            
    # Hiển thị dialog dựa trên biến trạng thái thay vì gọi trực tiếp trong nút bấm [cite: 64, 67]
    if st.session_state.show_tf_dialog:
        tf_window()

    with col2: 
        if st.button("Technical Indicator"):
            # Tương tự, gọi dialog Indicator ở đây nếu cần
            pass

    st.markdown('---')

    return st.session_state.tf_sellect