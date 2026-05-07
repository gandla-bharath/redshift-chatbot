"""
src/llm.py
----------
LLM connector — local Ollama (dev) or AWS Bedrock (prod).
Switch via LLM_MODE in .env: "local" or "aws"
"""

import os
import json
import logging
import re
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are an expert SQL data analyst assistant.

{schema}

RULES:
1. ALWAYS use the query_redshift tool to fetch data before answering.
2. Write only SELECT or WITH (CTE) queries — never INSERT/UPDATE/DELETE.
3. Always add LIMIT 50 unless the user asks for more.
4. If a query fails, try a simpler version.
5. Give clear, concise answers with key numbers highlighted.
6. If asked something unrelated to data, politely redirect.
"""


# ── Local Ollama ────────────────────────────────────────────────────────────

def chat_local(user_message: str, schema: str, history: list = []) -> dict:
    """
    Two-step local chat:
    1. Ask Ollama to generate SQL
    2. Return SQL so the notebook can execute and pass results back
    """
    import ollama

    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    client = ollama.Client(host=host)

    sql_prompt = f"""You are a SQL expert. Use ONLY the exact table and column names listed below.

SCHEMA:
- bookings(booking_id, property_id, user_id, checkin_date, checkout_date, amount, status, created_at)
- properties(property_id, name, city, country, category, price_per_night, host_id)
- users(user_id, name, email, country, signup_date)
- reviews(review_id, booking_id, rating, comment, created_at)

JOINS:
- reviews JOIN bookings ON reviews.booking_id = bookings.booking_id
- bookings JOIN properties ON bookings.property_id = properties.property_id
- bookings JOIN users ON bookings.user_id = users.user_id

RULES:
- Only SELECT queries, never INSERT/UPDATE/DELETE
- Always add LIMIT 50
- Return ONLY raw SQL — no explanation, no markdown, no backticks
- NEVER use a column that is not listed in the schema above

Question: {user_message}"""

    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": sql_prompt}]
    )
    raw_sql = resp["message"]["content"].strip()

    # Strip markdown code fences if model added them
    sql = re.sub(r"```(?:sql)?", "", raw_sql).replace("```", "").strip()
    return {"sql": sql, "mode": "local"}


def summarize_local(question: str, sql: str, results: str) -> str:
    """Ask Ollama to summarize query results in plain English."""
    import ollama

    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    client = ollama.Client(host=host)

    prompt = f"""You are a data analyst. Answer the user's question based on the SQL results.

Question: {question}

SQL Used:
{sql}

Results:
{results}

Give a clear, concise answer in 2-4 sentences. Highlight key numbers."""

    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp["message"]["content"].strip()


# ── AWS Bedrock ─────────────────────────────────────────────────────────────

def chat_bedrock(user_message: str, schema: str, history: list = [], run_query_fn=None) -> str:
    """
    Full agentic Bedrock chat with tool use loop.
    Bedrock generates SQL → run_query_fn executes it → Bedrock summarizes.
    """
    import boto3

    model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

    tools = [{
        "name": "query_redshift",
        "description": "Run a SQL SELECT query against the Redshift data warehouse and return results.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Valid SQL SELECT query with LIMIT"}
                },
                "required": ["sql"]
            }
        }
    }]

    system = [{"text": SYSTEM_PROMPT_TEMPLATE.format(schema=schema)}]
    messages = history + [{"role": "user", "content": user_message}]
    max_iterations = 8

    for _ in range(max_iterations):
        resp = client.converse(
            modelId=model_id,
            system=system,
            messages=messages,
            toolConfig={"tools": tools}
        )
        output_msg = resp["output"]["message"]
        messages.append(output_msg)
        stop_reason = resp["stopReason"]

        if stop_reason == "end_turn":
            for block in output_msg["content"]:
                if block.get("type") == "text":
                    return block["text"]
            return "No response generated."

        elif stop_reason == "tool_use":
            tool_results = []
            for block in output_msg["content"]:
                if block.get("type") == "tool_use" and block["name"] == "query_redshift":
                    sql = block["input"]["sql"]
                    try:
                        df = run_query_fn(sql)
                        result_str = df.to_string(index=False) if df is not None else "No results"
                        status = "success"
                    except Exception as e:
                        result_str = f"Error: {str(e)}"
                        status = "error"

                    tool_results.append({
                        "toolUseId": block["toolUseId"],
                        "content": [{"text": result_str}],
                        "status": status
                    })

            messages.append({
                "role": "user",
                "content": [{"type": "toolResult", **tr} for tr in tool_results]
            })

    return "Max iterations reached — query too complex. Try rephrasing."


# ── Unified entrypoint ──────────────────────────────────────────────────────

def get_sql(user_message: str, schema: str) -> str:
    """Generate SQL from natural language using configured LLM."""
    mode = os.getenv("LLM_MODE", "local").lower()
    if mode == "aws":
        raise RuntimeError("Use chat_bedrock() directly for AWS mode (handles full loop).")
    result = chat_local(user_message, schema)
    return result["sql"]


def summarize(question: str, sql: str, results: str) -> str:
    """Summarize query results in plain English."""
    mode = os.getenv("LLM_MODE", "local").lower()
    if mode == "aws":
        raise RuntimeError("AWS mode handles summarization internally in chat_bedrock().")
    return summarize_local(question, sql, results)