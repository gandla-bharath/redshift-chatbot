"""
src/db.py
---------
Database connector — works with local PostgreSQL (dev) and AWS Redshift (prod).
Switch via DB_MODE in .env: "local" or "aws"
"""

import os
import time
import logging
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ── Local PostgreSQL ────────────────────────────────────────────────────────

def get_local_connection():
    """Return a psycopg2 connection to local PostgreSQL."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "datawarehouse"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin123"),
    )


def run_local_query(sql: str, max_rows: int = None) -> pd.DataFrame:
    from sqlalchemy import create_engine, text
    max_rows = max_rows or int(os.getenv("MAX_ROWS", 50))
    _guard_select(sql)

    engine = create_engine(
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if len(df) > max_rows:
        df = df.head(max_rows)
    return df


# ── AWS Redshift Data API ───────────────────────────────────────────────────

def run_redshift_query(sql: str, max_rows: int = None) -> pd.DataFrame:
    """Execute SQL via Redshift Data API, return DataFrame."""
    import boto3
    max_rows = max_rows or int(os.getenv("MAX_ROWS", 50))
    _guard_select(sql)

    client = boto3.client("redshift-data", region_name=os.getenv("AWS_REGION", "us-east-1"))

    # Build kwargs — support both provisioned and serverless
    kwargs = {"Database": os.getenv("REDSHIFT_DB"), "Sql": sql}
    if os.getenv("REDSHIFT_CLUSTER_ID"):
        kwargs["ClusterIdentifier"] = os.getenv("REDSHIFT_CLUSTER_ID")
        kwargs["DbUser"] = os.getenv("REDSHIFT_DB_USER")
    elif os.getenv("REDSHIFT_WORKGROUP"):
        kwargs["WorkgroupName"] = os.getenv("REDSHIFT_WORKGROUP")

    if os.getenv("REDSHIFT_SECRET_ARN"):
        kwargs.pop("DbUser", None)
        kwargs["SecretArn"] = os.getenv("REDSHIFT_SECRET_ARN")

    logger.info(f"REDSHIFT SQL: {sql[:120]}")
    resp = client.execute_statement(**kwargs)
    stmt_id = resp["Id"]

    # Poll for result
    while True:
        detail = client.describe_statement(Id=stmt_id)
        status = detail["Status"]
        if status in ["FINISHED", "FAILED", "ABORTED"]:
            break
        time.sleep(0.8)

    if status != "FINISHED":
        raise Exception(f"Query {status}: {detail.get('Error', 'Unknown error')}")

    if not detail.get("HasResultSet", False):
        return pd.DataFrame()

    result = client.get_statement_result(Id=stmt_id)
    cols = [c["name"] for c in result["ColumnMetadata"]]
    rows = [[list(v.values())[0] for v in row] for row in result["Records"]]
    df = pd.DataFrame(rows, columns=cols)
    return df.head(max_rows)


# ── Unified entrypoint ──────────────────────────────────────────────────────

def run_query(sql: str, max_rows: int = None) -> pd.DataFrame:
    """
    Auto-route to local PostgreSQL or AWS Redshift based on DB_MODE env var.
    DB_MODE=local  → PostgreSQL (default)
    DB_MODE=aws    → Redshift Data API
    """
    mode = os.getenv("DB_MODE", "local").lower()
    if mode == "aws":
        return run_redshift_query(sql, max_rows)
    return run_local_query(sql, max_rows)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _guard_select(sql: str):
    """Reject any non-SELECT SQL as a safety guardrail."""
    cleaned = sql.strip().lstrip("(").upper()
    if not cleaned.startswith("SELECT") and not cleaned.startswith("WITH"):
        raise ValueError(f"Only SELECT/WITH queries allowed. Got: {sql[:60]}")


def test_connection() -> bool:
    """Smoke test — returns True if DB is reachable."""
    try:
        df = run_query("SELECT 1 AS ok")
        return df is not None and len(df) > 0
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False


def get_schema() -> str:
    """Auto-generate schema string from the database for use in LLM prompts."""
    sql = """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name, ordinal_position
    """
    df = run_query(sql, max_rows=500)
    schema_lines = ["Database Schema:"]
    current_table = None
    for _, row in df.iterrows():
        table = f"{row['table_schema']}.{row['table_name']}"
        if table != current_table:
            if current_table:
                schema_lines.append(")")
            schema_lines.append(f"\n{table} (")
            current_table = table
        schema_lines.append(f"  {row['column_name']} {row['data_type']},")
    if current_table:
        schema_lines.append(")")
    return "\n".join(schema_lines)
