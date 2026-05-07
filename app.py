"""
app.py
------
Streamlit chat UI with pgvector semantic cache.
Flow: Question → pgvector check → cache hit? return instantly : call LLM → store in cache
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
from src.cache import setup_cache_table, check_cache, store_cache, get_cache_stats, clear_cache

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Data Chatbot", page_icon="🤖", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0f172a; }
    .chat-user {
        background: #1e40af; color: white;
        padding: 12px 16px; border-radius: 12px 12px 4px 12px;
        margin: 8px 0; max-width: 80%; margin-left: auto; font-size: 15px;
    }
    .chat-bot {
        background: #1e293b; color: #e2e8f0;
        padding: 12px 16px; border-radius: 12px 12px 12px 4px;
        margin: 8px 0; max-width: 85%; font-size: 15px; border: 1px solid #334155;
    }
    .chat-cached {
        background: #14532d; color: #bbf7d0;
        padding: 12px 16px; border-radius: 12px 12px 12px 4px;
        margin: 8px 0; max-width: 85%; font-size: 15px; border: 1px solid #166534;
    }
    .sql-box {
        background: #0d1b2e; color: #7dd3fc;
        padding: 12px 16px; border-radius: 8px;
        font-family: monospace; font-size: 13px;
        border: 1px solid #1e3a5f; margin: 8px 0; white-space: pre-wrap;
    }
    .cache-badge {
        background: #166534; color: #bbf7d0;
        padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: bold;
    }
    .llm-badge {
        background: #1e3a5f; color: #7dd3fc;
        padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: bold;
    }
    .status-ok  { color: #10b981; font-weight: bold; }
    .status-err { color: #ef4444; font-weight: bold; }
    .metric-box {
        background: #1e293b; border: 1px solid #334155;
        border-radius: 8px; padding: 12px; text-align: center; margin: 4px 0;
    }
    .metric-num { font-size: 24px; font-weight: bold; color: #00d4ff; }
    .metric-lbl { font-size: 12px; color: #64748b; }
</style>
""", unsafe_allow_html=True)

# ── Init cache on startup ─────────────────────────────────────────────────────
@st.cache_resource
def init_cache():
    try:
        setup_cache_table()
        return True
    except Exception as e:
        return False

@st.cache_resource
def load_schema():
    return get_schema()

cache_ready = init_cache()
try:
    schema = load_schema()
except Exception:
    schema = ""

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    show_sql   = st.toggle("Show SQL", value=True)
    show_table = st.toggle("Show results table", value=True)
    max_rows   = st.slider("Max rows", 5, 100, 50)
    threshold  = st.slider("Cache threshold", 0.70, 1.00, 0.90, 0.01,
                           help="Similarity score needed to use cached answer")

    st.divider()
    st.markdown("### 🔌 Status")

    try:
        label = "✅ PostgreSQL" if test_connection() else "❌ PostgreSQL"
        color = "status-ok" if test_connection() else "status-err"
    except Exception:
        label, color = "❌ PostgreSQL", "status-err"
    st.markdown(f'<span class="{color}">{label}</span>', unsafe_allow_html=True)

    try:
        import ollama
        ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434")).list()
        st.markdown('<span class="status-ok">✅ Ollama</span>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<span class="status-err">❌ Ollama</span>', unsafe_allow_html=True)

    cache_label = "✅ pgvector cache" if cache_ready else "❌ pgvector cache"
    cache_color = "status-ok" if cache_ready else "status-err"
    st.markdown(f'<span class="{cache_color}">{cache_label}</span>', unsafe_allow_html=True)

    st.divider()
    st.markdown("### 📊 Cache Stats")
    if cache_ready:
        stats = get_cache_stats()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f'<div class="metric-box"><div class="metric-num">{stats.get("total_entries",0)}</div><div class="metric-lbl">Stored</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-box"><div class="metric-num">{stats.get("total_hits",0)}</div><div class="metric-lbl">Hits</div></div>', unsafe_allow_html=True)
        if st.button("🗑️ Clear cache", use_container_width=True):
            clear_cache()
            st.success("Cache cleared!")
            st.rerun()

    st.divider()
    st.markdown("### 💡 Try These")
    samples = [
        "How many total bookings?",
        "Top 5 cities by properties",
        "Total revenue from completed bookings",
        "Highest rated property category",
        "Monthly bookings in 2023",
        "Users per country",
    ]
    for q in samples:
        if st.button(q, use_container_width=True):
            st.session_state.sample_question = q

    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("## 🤖 Data Chatbot")
st.markdown("Ask questions about your data in plain English")
st.caption(f"Cache threshold: {threshold} · Max rows: {max_rows}")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Render history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(f'<div class="chat-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)
    else:
        css   = "chat-cached" if msg.get("from_cache") else "chat-bot"
        badge = (f'<span class="cache-badge">⚡ Cache · {msg.get("similarity","")} similarity</span>'
                 if msg.get("from_cache")
                 else '<span class="llm-badge">🧠 LLM</span>')
        st.markdown(f'<div class="{css}">{badge}<br><br>{msg["content"]}</div>', unsafe_allow_html=True)
        if msg.get("sql") and show_sql:
            st.markdown(f'<div class="sql-box">📝 SQL:\n{msg["sql"]}</div>', unsafe_allow_html=True)
        if msg.get("df") is not None and show_table and len(msg["df"]) > 0:
            st.dataframe(msg["df"], use_container_width=True)

# ── Handle input ──────────────────────────────────────────────────────────────
default_input = ""
if "sample_question" in st.session_state:
    default_input = st.session_state.pop("sample_question")

user_input = st.chat_input("Ask a question about your data...")
question = user_input or default_input

if question:
    st.markdown(f'<div class="chat-user">👤 {question}</div>', unsafe_allow_html=True)
    st.session_state.messages.append({"role": "user", "content": question})

    # ── 1. Check pgvector cache first ─────────────────────────────────────────
    cached = None
    if cache_ready:
        with st.spinner("🔍 Checking semantic cache..."):
            cached = check_cache(question)
            if cached and cached.get("similarity", 0) < threshold:
                cached = None  # below threshold, treat as miss

    if cached:
        answer = cached["answer"]
        sql    = cached["sql"]
        sim    = cached["similarity"]

        st.markdown(
            f'<div class="chat-cached">'
            f'<span class="cache-badge">⚡ Cache hit · {sim} similarity</span>'
            f'<br><br>{answer}</div>',
            unsafe_allow_html=True
        )
        if show_sql:
            st.markdown(f'<div class="sql-box">📝 SQL (cached):\n{sql}</div>', unsafe_allow_html=True)

        st.session_state.messages.append({
            "role": "assistant", "content": answer,
            "sql": sql, "df": None, "from_cache": True, "similarity": sim
        })

    else:
        # ── 2. Cache miss — call LLM ──────────────────────────────────────────
        with st.spinner("🧠 Generating SQL with LLM..."):
            try:
                sql = get_sql(question, schema)
            except Exception as e:
                st.error(f"LLM error: {e}")
                st.stop()

        with st.spinner("⚙️ Running query on database..."):
            try:
                df = run_query(sql, max_rows=max_rows)
                results_str = df.to_string(index=False) if df is not None and len(df) > 0 else "No results"
            except Exception as e:
                st.error(f"Query failed: {e}\n\nGenerated SQL:\n{sql}")
                st.stop()

        with st.spinner("✍️ Summarizing results..."):
            try:
                answer = summarize(question, sql, results_str)
            except Exception as e:
                answer = f"Returned {len(df)} rows. (Summary unavailable)"

        st.markdown(
            f'<div class="chat-bot">'
            f'<span class="llm-badge">🧠 LLM generated</span>'
            f'<br><br>{answer}</div>',
            unsafe_allow_html=True
        )
        if show_sql:
            st.markdown(f'<div class="sql-box">📝 SQL:\n{sql}</div>', unsafe_allow_html=True)
        if show_table and df is not None and len(df) > 0:
            st.dataframe(df, use_container_width=True)

        # ── 3. Store result in pgvector cache ─────────────────────────────────
        if cache_ready:
            store_cache(question, sql, answer)
            st.caption("✅ Answer cached for future similar questions")

        st.session_state.messages.append({
            "role": "assistant", "content": answer,
            "sql": sql, "df": df, "from_cache": False
        })
