import streamlit as st

# Define pages with proper Material icon shortcodes
chat_page = st.Page("page_chat.py", title="Chat", icon=":material/chat:")
detail_page = st.Page("page_detail.py", title="Debug", icon=":material/search:")

# Create navigation with the defined pages
pg = st.navigation([chat_page, detail_page])

# Set page configuration
st.set_page_config(page_title="Recommendation System", page_icon=":material/shopping_cart:")

# Run the navigation
pg.run()