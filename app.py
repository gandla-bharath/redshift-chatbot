"""
app.py
------
Streamlit chat UI — ask questions in plain English, get SQL + results + answer.
Run: streamlit run app.py
"""

import os
import sys
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from src.db import run_query, get_schema, test_connection
from src.llm import get_sql, summarize

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Data Chatbot",
    page_icon="🤖",
    layout="wide"
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0f172a; }
    .stApp { background-color: #0f172a; }

    .chat-user {
        background: #1e40af;
        color: white;
        padding: 12px 16px;
        border-radius: 12px 12px 4px 12px;
        margin: 8px 0;
        max-width: 80%;
        margin-left: auto;
        font-size: 15px;
    }
    .chat-bot {
        background: #1e293b;
        color: #e2e8f0;
        padding: 12px 16px;
        border-radius: 12px 12px 12px 4px;
        margin: 8px 0;
        max-width: 85%;
        font-size: 15px;
        border: 1px solid #334155;
    }
    .sql-box {
        background: #0d1b2e;
        color: #7dd3fc;
        padding: 12px 16px;
        border-radius: 8px;
        font-family: monospace;
        font-size: 13px;
        border: 1px solid #1e3a5f;
        margin: 8px 0;
    }
    .status-ok  { color: #10b981; font-weight: bold; }
    .status-err { color: #ef4444; font-weight: bold; }
    .header-title {
        font-size: 28px;
        font-weight: 700;
        color: #00d4ff;
        margin-bottom: 4px;
    }
    .header-sub {
        color: #64748b;
        font-size: 14px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Settings")

    show_sql = st.toggle("Show generated SQL", value=True)
    show_table = st.toggle("Show results table", value=True)
    max_rows = st.slider("Max rows", 5, 100, 50)

    st.divider()
    st.markdown("### 🔌 Connection Status")

    # DB status
    try:
        ok = test_connection()
        if ok:
            st.markdown('<span class="status-ok">✅ PostgreSQL connected</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-err">❌ DB not connected</span>', unsafe_allow_html=True)
    except Exception as e:
        st.markdown(f'<span class="status-err">❌ {str(e)[:40]}</span>', unsafe_allow_html=True)

    # Ollama status
    try:
        import ollama
        client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        client.list()
        st.markdown('<span class="status-ok">✅ Ollama running</span>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<span class="status-err">❌ Ollama not running</span>', unsafe_allow_html=True)

    st.divider()
    st.markdown("### 💡 Sample Questions")
    samples = [
        "How many total bookings?",
        "Top 5 cities by properties",
        "Total revenue from completed bookings",
        "Average rating by property category",
        "Monthly bookings in 2023",
        "How many users per country?",
        "Most expensive properties",
    ]
    for q in samples:
        if st.button(q, use_container_width=True):
            st.session_state.sample_question = q

    st.divider()
    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ── Main area ────────────────────────────────────────────────────────────────
st.markdown('<div class="header-title">🤖 Data Chatbot</div>', unsafe_allow_html=True)
st.markdown('<div class="header-sub">Ask questions about your data in plain English</div>', unsafe_allow_html=True)

# Load schema once
@st.cache_resource
def load_schema():
    return get_schema()

try:
    schema = load_schema()
except Exception as e:
    st.error(f"Could not load schema: {e}")
    schema = ""

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render chat history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(f'<div class="chat-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="chat-bot">🤖 {msg["content"]}</div>', unsafe_allow_html=True)
        if "sql" in msg and show_sql:
            st.markdown(f'<div class="sql-box">📝 SQL:<br>{msg["sql"]}</div>', unsafe_allow_html=True)
        if "df" in msg and show_table and msg["df"] is not None:
            st.dataframe(msg["df"], use_container_width=True)

# ── Input ────────────────────────────────────────────────────────────────────
# Handle sample question click
default_input = ""
if "sample_question" in st.session_state:
    default_input = st.session_state.pop("sample_question")

user_input = st.chat_input("Ask a question about your data...", )

# Also accept sample question
question = user_input or default_input

if question:
    # Show user message
    st.markdown(f'<div class="chat-user">👤 {question}</div>', unsafe_allow_html=True)
    st.session_state.messages.append({"role": "user", "content": question})

    with st.spinner("Thinking..."):
        try:
            # Step 1: Generate SQL
            sql = get_sql(question, schema)

            # Step 2: Run SQL
            df = run_query(sql, max_rows=max_rows)

            # Step 3: Summarize
            results_str = df.to_string(index=False) if df is not None and len(df) > 0 else "No results found"
            answer = summarize(question, sql, results_str)

            # Show response
            st.markdown(f'<div class="chat-bot">🤖 {answer}</div>', unsafe_allow_html=True)
            if show_sql:
                st.markdown(f'<div class="sql-box">📝 SQL:<br>{sql}</div>', unsafe_allow_html=True)
            if show_table and df is not None and len(df) > 0:
                st.dataframe(df, use_container_width=True)

            # Save to history
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "sql": sql,
                "df": df
            })

        except Exception as e:
            err = f"Error: {str(e)}"
            st.markdown(f'<div class="chat-bot">❌ {err}</div>', unsafe_allow_html=True)
            st.session_state.messages.append({"role": "assistant", "content": err})