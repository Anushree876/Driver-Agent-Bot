"""
frontend.py — Streamlit Chat Interface for Drive Search Agent

HOW IT WORKS:
1. User types a message in the chat input
2. Streamlit sends it to the FastAPI backend via HTTP POST /chat
3. Backend agent processes it and returns a response
4. Response is displayed in the chat UI with markdown rendering

SETUP:
  pip install streamlit requests

RUN:
  streamlit run frontend.py

ENV VARIABLES (optional, can also be typed in sidebar):
  BACKEND_URL=https://conversation-bot-1jeh.onrender.com
"""

import streamlit as st
import requests
import uuid

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Drive Search Agent",
    page_icon="🔍",
    layout="centered"
)

# ─────────────────────────────────────────────
# CUSTOM STYLES — clean, modern look
# ─────────────────────────────────────────────

st.markdown("""
<style>
    /* Main background */
    .stApp {
        background-color: #0f1117;
        color: #e0e0e0;
    }

    /* Title */
    h1 {
        font-family: 'Georgia', serif;
        color: #4fc3f7;
        text-align: center;
    }

    /* Sidebar */
    .css-1d391kg {
        background-color: #1a1d24;
    }

    /* Chat message bubbles */
    .user-msg {
        background: #1e3a5f;
        border-radius: 16px 16px 4px 16px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
        float: right;
        clear: both;
        color: #e8f4fd;
        font-size: 15px;
    }

    .bot-msg {
        background: #1a2332;
        border: 1px solid #2a4060;
        border-radius: 16px 16px 16px 4px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 85%;
        float: left;
        clear: both;
        color: #d0e8ff;
        font-size: 15px;
    }

    /* Make links visible */
    a {
        color: #4fc3f7 !important;
    }

    /* Clear float after messages */
    .clearfix::after {
        content: "";
        display: table;
        clear: both;
    }

    /* Input box */
    .stTextInput > div > div > input {
        background-color: #1a1d24;
        color: #e0e0e0;
        border: 1px solid #2a4060;
        border-radius: 8px;
    }

    /* Buttons */
    .stButton > button {
        background-color: #1e3a5f;
        color: #4fc3f7;
        border: 1px solid #2a4060;
        border-radius: 8px;
        width: 100%;
    }

    .stButton > button:hover {
        background-color: #2a4f7f;
        border-color: #4fc3f7;
    }

    /* Typing indicator */
    .typing-indicator {
        color: #4fc3f7;
        font-style: italic;
        font-size: 13px;
        padding: 4px 8px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────

# Unique session ID per browser tab (so different users have separate histories)
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

# Chat history: list of {"role": "user"/"assistant", "content": "..."}
if "messages" not in st.session_state:
    st.session_state.messages = []

# Backend URL
if "backend_url" not in st.session_state:
    st.session_state.backend_url = "https://conversation-bot-1jeh.onrender.com"


# ─────────────────────────────────────────────
# SIDEBAR — settings + example queries
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Settings")

    backend_url = st.text_input(
        "Backend URL",
        value=st.session_state.backend_url,
        help="URL of your FastAPI backend"
    )
    st.session_state.backend_url = backend_url

    # Health check button
    if st.button("🔌 Test Connection"):
        try:
            resp = requests.get(f"{backend_url}/", timeout=5)
            if resp.status_code == 200:
                st.success("✅ Backend is running!")
            else:
                st.error(f"❌ Status {resp.status_code}")
        except Exception as e:
            st.error(f"❌ Cannot connect: {e}")

    st.divider()

    st.markdown("## 💡 Example Queries")
    examples = [
        "Show me all PDF files",
        "Find files with 'report' in the name",
        "What images are in the folder?",
        "Show Google Sheets files",
        "Find files modified after January 2024",
        "Search for files containing 'budget'",
        "List all Google Docs",
        "Find files with 'invoice' in the name that are PDFs",
    ]

    for example in examples:
        if st.button(f"▶ {example}", key=f"ex_{example}"):
            # Inject example into chat as if user typed it
            st.session_state.pending_message = example

    st.divider()

    # Clear chat button
    if st.button("🗑️ Clear Conversation"):
        st.session_state.messages = []
        # Also clear backend history
        try:
            requests.delete(
                f"{backend_url}/chat/{st.session_state.session_id}",
                timeout=5
            )
        except Exception:
            pass
        st.session_state.session_id = str(uuid.uuid4())  # new session
        st.rerun()

    st.divider()
    st.markdown(
        "<small style='color:#666'>Session: "
        f"`{st.session_state.session_id[:8]}...`</small>",
        unsafe_allow_html=True
    )


# ─────────────────────────────────────────────
# MAIN TITLE
# ─────────────────────────────────────────────

st.markdown("# 🔍 Drive Search Agent")
st.markdown(
    "<p style='text-align:center; color:#888; font-size:14px;'>"
    "Ask me to find any file in your Google Drive folder</p>",
    unsafe_allow_html=True
)
st.divider()


# ─────────────────────────────────────────────
# HELPER: CALL BACKEND
# ─────────────────────────────────────────────

def call_backend(user_message: str) -> str:
    """Send message to FastAPI backend and get the agent's response."""
    try:
        resp = requests.post(
            f"{st.session_state.backend_url}/chat",
            json={
                "message": user_message,
                "session_id": st.session_state.session_id
            },
            timeout=60  # Drive API can be slow, give it time
        )
        if resp.status_code == 200:
            return resp.json()["reply"]
        else:
            return f"❌ Backend error {resp.status_code}: {resp.text}"
    except requests.exceptions.ConnectionError:
        return (
            "❌ Cannot connect to backend. Make sure FastAPI is running at: "
            f"`{st.session_state.backend_url}`"
        )
    except requests.exceptions.Timeout:
        return "⏱️ Request timed out. The Drive API might be slow, try again."
    except Exception as e:
        return f"❌ Unexpected error: {str(e)}"


# ─────────────────────────────────────────────
# CHAT DISPLAY
# ─────────────────────────────────────────────

# Show all previous messages
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(msg["content"])


# ─────────────────────────────────────────────
# HANDLE EXAMPLE BUTTON CLICKS
# ─────────────────────────────────────────────

if "pending_message" in st.session_state:
    pending = st.session_state.pop("pending_message")

    # Add user message to display
    st.session_state.messages.append({"role": "user", "content": pending})

    with st.chat_message("user", avatar="👤"):
        st.markdown(pending)

    # Get response
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Searching your Drive..."):
            response = call_backend(pending)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()


# ─────────────────────────────────────────────
# CHAT INPUT
# ─────────────────────────────────────────────

if user_input := st.chat_input("Ask me to find files... e.g. 'Show all PDFs'"):

    # Display user message immediately
    with st.chat_message("user", avatar="👤"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Call backend and stream response
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("🔍 Searching your Drive..."):
            response = call_backend(user_input)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})


# ─────────────────────────────────────────────
# EMPTY STATE — show when no messages yet
# ─────────────────────────────────────────────

if not st.session_state.messages:
    st.markdown("""
    <div style="text-align:center; padding: 40px; color: #555;">
        <div style="font-size: 48px; margin-bottom: 16px;">📁</div>
        <p style="font-size: 16px;">Start by asking me to find files!</p>
        <p style="font-size: 13px;">Try the example queries in the sidebar →</p>
    </div>
    """, unsafe_allow_html=True)