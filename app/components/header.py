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


@st.dialog("Technical Indicator")
def ti_window():
    # Tiêu đề cột (nếu cần)
    # col1, col2, col3, col4 = st.columns([1, 1, 1, 0.5])
    
    # Giả lập danh sách các cấu hình MA
    for i in range(1, 4):
        key_check = f"ma{i}_enabled"
        key_val = f"ma{i}_val"
        key_type = f"ma{i}_type"
        key_color = f"ma{i}_color"
        
        # Khởi tạo mặc định nếu chưa có
        if key_check not in st.session_state: st.session_state[key_check] = True
        if key_val not in st.session_state: st.session_state[key_val] = [7, 25, 99][i-1]
        
        c1, c2, c3, c4 = st.columns([1, 1, 1, 0.5])
        
        with c1:
            st.checkbox(f"MA{i}", key=key_check)
        with c2:
            st.number_input("", value=st.session_state[key_val], key=key_val, label_visibility="collapsed")
        with c3:
            st.selectbox("", ["Close", "Open", "High", "Low"], key=key_type, label_visibility="collapsed")
        with c4:
            st.color_picker("", "#FFD700" if i==1 else "#FF69B4", key=key_color, label_visibility="collapsed")

    # Nút chức năng ở cuối
    col_btn1, col_btn2 = st.columns([1, 1])
    if col_btn1.button("Đặt lại"):
        # Reset logic tại đây
        st.rerun()
    if col_btn2.button("Lưu lại"):
        st.success("Đã lưu cấu hình!")
        st.rerun()


def render_header():
    """Tạo header điều khiển khung thời gian."""
    # Khởi tạo an toàn trong hàm 
    if "tf_sellect" not in st.session_state:
        st.session_state.tf_sellect = "1min"

    if "show_tf_dialog" not in st.session_state:
        st.session_state.show_tf_dialog = False
    if "show_ti_dialog" not in st.session_state:
        st.session_state.show_ti_dialog = False
    

    st.markdown("### 🛠 Công cụ điều khiển")
    
    col1, col2 = st.columns([3, 1])

    with col1:
        if st.button("Time Frame"): 
            st.session_state.show_tf_dialog = True
            st.rerun()
            
    if st.session_state.show_tf_dialog:
        tf_window()

    with col2:
        if st.button("Technical Indicator"): 
            st.session_state.show_ti_dialog = True
            st.rerun()
            
    if st.session_state.show_ti_dialog:
        ti_window()

    st.markdown('---')

    return st.session_state.tf_sellect