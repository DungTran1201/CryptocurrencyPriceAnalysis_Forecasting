import streamlit as st

from config import OperationLogger

op_log = OperationLogger("Technical - OP")

def render_indicator_settings(indicator_name: str, 
                              max_items: int = 6):
    """
    Render giao diện cấu hình cho chỉ báo bất kỳ.
    Trả về dictionary cấu hình nếu nhấn lưu.
    """
    settings = {indicator_name: []}
    
    st.subheader(f"Setup {indicator_name}")
    
    for i in range(1, max_items + 1):
        key_enabled = f"{indicator_name}_{i}_enabled"
        key_window = f"{indicator_name}_{i}_window"
        key_col = f"{indicator_name}_{i}_col"
        key_color = f"{indicator_name}_{i}_color"
        
        # Khởi tạo mặc định trong session_state
        if key_enabled not in st.session_state: st.session_state[key_enabled] = False
        if key_window not in st.session_state: st.session_state[key_window] = 14
        if key_col not in st.session_state: st.session_state[key_col] = "Close"

        # Bố cục hàng
        cols = st.columns([1, 1, 1, 1])
        with cols[0]:
            enabled = st.checkbox(f"{indicator_name}{i}", 
                                  key=key_enabled)
        with cols[1]:
            window = st.number_input(f"{indicator_name}{i}", 
                                     st.session_state[key_window], 
                                     key=key_window, 
                                     label_visibility="collapsed")
        with cols[2]:
            col_type = st.selectbox(f"{indicator_name}{i}", 
                                    ["Close", "Open", "High", "Low"], 
                                    key=key_col, 
                                    label_visibility="collapsed")

        with cols[3]:
            line_color = st.color_picker(f"{indicator_name}{i}", 
                                         "#FFD700" if i==1 else "#FF69B4", 
                                         key=key_color, 
                                         label_visibility="collapsed")  
            
        if enabled:
            settings[indicator_name].append({
                "id": i,
                "column": col_type,
                "window": window, 
                "color": line_color
            })
            
    return settings


def indicator_selected(indicator_name: str) : 
    if st.button(indicator_name): 
        st.session_state.active_indicator_dialog = indicator_name
        st.rerun()


@st.dialog("Technical Indicator")
def ti_window():

    col1, col2 = st.columns([1, 4])

    with col1:
        for i in st.session_state.indicators_name:
            indicator_selected(i)
        
    with col2:
            
        if st.session_state.active_indicator_dialog == "SMA":
            sma_key = render_indicator_settings(indicator_name="SMA")
            st.session_state.ti_select["SMA"] = sma_key["SMA"]
            op_log.info(f"""Session state ti select update key 
                        SMA: {st.session_state.ti_select["SMA"]}""")
        
        if st.session_state.active_indicator_dialog == "EMA":
            ema_key = render_indicator_settings(indicator_name="EMA")
            st.session_state.ti_select["EMA"] = ema_key["EMA"]
            op_log.info(f"""Session state ti select update key 
                        EMA: {st.session_state.ti_select["EMA"]}""")

        if st.session_state.active_indicator_dialog == "BOLL":
            boll_key = render_indicator_settings(indicator_name="BOLL")
            st.session_state.ti_select["BOLL"] = boll_key["BOLL"]
            op_log.info(f"""Session state ti select update key 
                        BOLL: {st.session_state.ti_select["BOLL"]}""")

        if st.session_state.active_indicator_dialog == "RSI":
            rsi_key = render_indicator_settings(indicator_name="RSI")
            st.session_state.ti_select["RSI"] = rsi_key["RSI"]
            op_log.info(f"""Session state ti select update key 
                        RSI: {st.session_state.ti_select["RSI"]}""")

        # Nút chức năng ở cuối
        col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
        if col_btn1.button("Reset"):
            st.rerun()
        if col_btn2.button("Save"):
            st.rerun()
        if col_btn3.button("Exit"): 
            st.session_state.active_header_dialog = None
            st.rerun()

        
