import streamlit as st

# Set up page configuration
st.set_page_config(
    page_title="Crypto Intelligence System",
    page_icon="🚀",
    layout="wide"
)

def render_sidebar():
    """Renders the navigation sidebar with project functions."""

def render_main_page():
    """Renders the introduction of the system in the main area."""
    st.title("Welcome to the Crypto Prediction System 🚀")
    
    st.subheader("About the System")
    st.markdown("""
    This platform is a comprehensive **Agentic RAG-powered system** designed to predict 
    cryptocurrency trends and price movements. By integrating advanced machine learning 
    models with real-time market data, we provide actionable insights for traders.
    """)
    
    st.info("""
    ### Core Capabilities:
    * **Data Ingestion:** Automated high-speed data collection from Binance API.
    * **Predictive Analytics:** Deep learning models built on **PyTorch** to forecast 
        price trends.
    * **Agentic RAG:** Leveraging the **Gemini API** as an intelligent agent to analyze 
        market conditions and provide context-aware responses.
    * **Real-time Visualization:** Interactive charts via Streamlit for better data 
        interpretation.
    """)
    
    st.warning("Please navigate to the specific functions using the sidebar menu on the left.")

# Run the UI components
if __name__ == "__main__":
    render_sidebar()
    render_main_page()