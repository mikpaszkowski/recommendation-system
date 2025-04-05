# Fix for PyTorch/Streamlit compatibility and tokenizers warnings
import os
os.environ["STREAMLIT_SERVER_WATCH_DIRS"] = "false"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import streamlit as st
from typing import List, Dict
import datetime
import json
import logging
import sys
from pathlib import Path

# Add the project root directory to the Python path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

# Import the service factory
from src.factories.service_factory import ServiceFactory

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
    if 'initialized' not in st.session_state:
        st.session_state.initialized = False

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

def initialize_services():
    """Initialize application services using the factory."""
    if st.session_state.initialized:
        return
        
    # Display a spinner during initialization
    with st.spinner('Initializing recommendation system...'):
        try:
            # Get service factory
            factory = ServiceFactory()
            
            # Initialize dialog manager (this will initialize all dependencies)
            factory.get_dialog_manager()
            
            st.session_state.initialized = True
            logger.info("Application services initialized")
        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}")
            st.error(f"Failed to initialize recommendation system: {str(e)}")

def main():
    st.title("Product Recommendation Chat")
    st.subheader("What do you want to buy?")
    
    # Initialize session state
    initialize_session_state()
    
    # Initialize services (only happens once)
    initialize_services()
    
    # Display chat messages
    display_messages()
    
    # Only enable chat input if initialization was successful
    if st.session_state.initialized:
        # Chat input
        if user_input := st.chat_input("Type your message here..."):
            # Add user message to chat
            add_message("user", user_input)
            
            # Process user input through dialog manager
            try:
                # Get service factory and dialog manager
                factory = ServiceFactory()
                dialog_manager = factory.get_dialog_manager()
                
                # Use the dialog manager to process the query
                response = dialog_manager.manage(
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
    else:
        st.warning("Please wait, the recommendation system is still initializing...")

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