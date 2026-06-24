import streamlit as st

from config import OperationLogger, ExceptionLogger

# Initialize Loggers
op_log = OperationLogger("TimeFrame - OP")
ex_log = ExceptionLogger("TimeFrame - EX")


@st.dialog("TimeFrame")
def tf_window():
    
    col1, col2 = st.columns([1, 1])

    with col1: 
        timeframes = ['5min', '15min', '30min', '1h', '4h', '1d']
        selected_tf = st.radio("Select Timeframe:", timeframes, horizontal=True)
    with col2: 
        custom_tf = st.text_input("Custom (vd: 2H, 3D):", placeholder="Enter...")    

    if st.button("Submit"):
        st.session_state.tf_select = custom_tf if custom_tf else selected_tf
        op_log.info(f"Select TF: {st.session_state.tf_select}")
        st.session_state.active_header_dialog = None
        st.rerun()