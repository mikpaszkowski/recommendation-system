import streamlit as st
from typing import List, Dict
import datetime
import os
import json
import logging
import sys
from pathlib import Path

# Add the project root directory to the Python path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

# Now import from the src package
from src.llm_interface.recommendation_api import RecommendationAPI
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.dialog_manager.simple_dialog_manager import SimpleDialogManager
from src.recommendation_engine.recommenders.content_hybrid_item_based_rec import ContentHybridItemBasedRec

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default user ID and recommendations count
DEFAULT_USER_ID = 'AHPJHWUFX7DFIVS5B3XNEK7JLSAQ'
DEFAULT_NUM_RECOMMENDATIONS = 5

def initialize_session_state():
    """Initialize session state variables if they don't exist."""
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'user_input' not in st.session_state:
        st.session_state.user_input = ''
    if 'dialog_manager' not in st.session_state:
        # Initialize components
        try:
            content_hybrid_item_based_rec = ContentHybridItemBasedRec()
            content_hybrid_item_based_rec_model = content_hybrid_item_based_rec.get_model()
        
            recommendation_api = RecommendationAPI(
                recommender=content_hybrid_item_based_rec_model
            )
            llm_handler = SimpleLLMHandler(api_key=os.getenv("OPENAI_API_KEY"))
            st.session_state.dialog_manager = SimpleDialogManager(
                recommendation_api=recommendation_api,
                llm_handler=llm_handler
            )
            logger.info("Dialog manager initialized in session state")
        except Exception as e:
            logger.error(f"Failed to initialize dialog manager: {str(e)}")
            st.error(f"Failed to initialize recommendation system: {str(e)}")

def add_message(role: str, content: str):
    """Add a message to the chat history."""
    st.session_state.messages.append({
        'role': role,
        'content': content,
        'timestamp': datetime.datetime.now().strftime("%H:%M")
    })

def display_messages():
    """Display all messages in the chat."""
    for message in st.session_state.messages:
        with st.chat_message(message['role']):
            st.write(f"{message['content']}")
            st.caption(f"Sent at {message['timestamp']}")

def main():
    st.title("Product Recommendation Chat")
    st.subheader("What do you want to buy?")
    
    # Initialize session state
    initialize_session_state()
    
    # Display chat messages
    display_messages()
    
    # Chat input
    if user_input := st.chat_input("Type your message here..."):
        # Add user message to chat
        add_message("user", user_input)
        
        # Process user input through dialog manager
        try:
            # Use the dialog manager to process the query
            response = st.session_state.dialog_manager.manage(
                user_query=user_input,
                user_id=DEFAULT_USER_ID,
                num_recommendations=DEFAULT_NUM_RECOMMENDATIONS
            )
            
            # Add assistant response to chat
            add_message("assistant", response)
            
        except Exception as e:
            error_message = f"I'm sorry, something went wrong: {str(e)}"
            add_message("assistant", error_message)
            logger.error(f"Error processing query: {str(e)}")
        
        # Force a rerun to display the new messages
        st.rerun()

if __name__ == "__main__":
    # Set Streamlit page config
    st.set_page_config(
        page_title="Product Recommendation Chat",
        page_icon="🛍️",
        layout="centered"
    )
    
    # Add some custom CSS
    st.markdown("""
        <style>
        .stChat {
            padding: 20px;
        }
        .stChatMessage {
            margin: 10px 0;
        }
        .stTextInput {
            margin-top: 20px;
        }
        </style>
    """, unsafe_allow_html=True)
    
    main() 