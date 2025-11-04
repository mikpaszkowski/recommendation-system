

import streamlit as st

st.title("🔎 Debug")

if 'debug_info' in st.session_state:
    if 'user_input' in st.session_state.debug_info:
        with st.expander("View User Input", expanded=True):
            st.write(st.session_state.debug_info['user_input'])
    else:
        st.info("No user input data available yet. Try having a conversation in the chat first!")

    if 'preferences' in st.session_state.debug_info:
        # Create an expander for preferences
        with st.expander("View Extracted Preferences", expanded=True):
            # Format the JSON data nicely
            st.json(st.session_state.debug_info['preferences'])
    else:
        st.info("No preferences data available yet. Try having a conversation in the chat first!")

    if 'prompt' in st.session_state.debug_info:
        with st.expander("View Prompt", expanded=True):
            st.write(st.session_state.debug_info['prompt'])
    else:
        st.info("No prompt data available yet. Try having a conversation in the chat first!")
        
    if 'recommendations' in st.session_state.debug_info:
        with st.expander("View Recommendations", expanded=True):
            st.json(st.session_state.debug_info['recommendations'])
    else:
        st.info("No recommendations data available yet. Try having a conversation in the chat first!")
else:
    st.info("No debug information available yet. Try having a conversation in the chat first!")
