"""
src/cache.py
------------
Semantic cache using pgvector + Ollama embeddings.
- Uses Ollama (already running) to generate embeddings — no extra packages needed
- Stores Q&A pairs as vectors in PostgreSQL
- Before calling LLM, checks for similar past questions
"""

import os
import logging
import psycopg2
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

CACHE_THRESHOLD = float(os.getenv("CACHE_THRESHOLD", "0.80"))
OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL     = os.getenv("EMBED_MODEL", "nomic-embed-text")  # 768 dims
VECTOR_DIM      = 768


def _get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5433)),
        database=os.getenv("DB_NAME", "datawarehouse"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin123"),
    )


def embed(text: str) -> list[float]:
    """Generate embedding using Ollama — no extra packages needed."""
    import urllib.request, json
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["embedding"]


def setup_cache_table():
    """Create pgvector cache table. Call once on startup."""
    conn = _get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS question_cache (
                id          SERIAL PRIMARY KEY,
                question    TEXT NOT NULL,
                sql         TEXT NOT NULL,
                answer      TEXT NOT NULL,
                embedding   vector({VECTOR_DIM}),
                hit_count   INT DEFAULT 1,
                created_at  TIMESTAMP DEFAULT NOW(),
                last_hit_at TIMESTAMP DEFAULT NOW()
            );
        """)
        conn.commit()
        print("✅ pgvector cache table ready")
    except Exception as e:
        conn.rollback()
        print(f"❌ Cache table setup failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def check_cache(question: str, threshold: float = None) -> dict | None:
    """Check pgvector for a similar past question."""
    use_threshold = threshold if threshold is not None else CACHE_THRESHOLD
    try:
        vec      = embed(question)
        vec_str  = f"[{','.join(map(str, vec))}]"
        conn     = _get_conn()
        cur      = conn.cursor()

        # Debug — show top scores
        cur.execute("""
            SELECT question, 1 - (embedding <=> %s::vector) AS score
            FROM question_cache
            ORDER BY score DESC LIMIT 5
        """, (vec_str,))
        rows = cur.fetchall()
        print(f"\n🔍 Cache search: '{question[:60]}'")
        print(f"   Threshold: {use_threshold}")
        if rows:
            for r in rows:
                tag = "✅ HIT" if r[1] >= use_threshold else "❌ miss"
                print(f"   {tag} | score={r[1]:.4f} | '{r[0][:55]}'")
        else:
            print("   Cache is empty")

        # Fetch best match above threshold
        cur.execute("""
            SELECT id, question, sql, answer,
                   1 - (embedding <=> %s::vector) AS score
            FROM question_cache
            WHERE 1 - (embedding <=> %s::vector) >= %s
            ORDER BY score DESC LIMIT 1
        """, (vec_str, vec_str, use_threshold))

        row = cur.fetchone()
        if row:
            cache_id, cached_q, cached_sql, cached_ans, score = row
            cur.execute("""
                UPDATE question_cache
                SET hit_count = hit_count + 1, last_hit_at = NOW()
                WHERE id = %s
            """, (cache_id,))
            conn.commit()
            print(f"   → CACHE HIT (score={score:.4f})")
            return {
                "question": cached_q, "sql": cached_sql,
                "answer": cached_ans, "similarity": round(score, 3),
                "from_cache": True
            }

        print("   → CACHE MISS — calling LLM")
        return None

    except Exception as e:
        print(f"   ⚠️  Cache error: {e}")
        logger.warning(f"Cache check failed: {e}")
        return None
    finally:
        try: cur.close(); conn.close()
        except: pass


def store_cache(question: str, sql: str, answer: str) -> bool:
    """Store a Q&A pair in pgvector cache."""
    try:
        vec     = embed(question)
        vec_str = f"[{','.join(map(str, vec))}]"
        conn    = _get_conn()
        cur     = conn.cursor()
        cur.execute("""
            INSERT INTO question_cache (question, sql, answer, embedding)
            VALUES (%s, %s, %s, %s::vector)
        """, (question, sql, answer, vec_str))
        conn.commit()
        cur.close(); conn.close()
        print(f"✅ Cached: '{question[:60]}'")
        return True
    except Exception as e:
        print(f"❌ Cache store failed: {e}")
        return False


def get_cache_stats() -> dict:
    """Return cache stats for UI display."""
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(hit_count) - COUNT(*), 0),
                   MAX(last_hit_at), MAX(created_at)
            FROM question_cache
        """)
        r = cur.fetchone()
        cur.close(); conn.close()
        return {
            "total_entries": r[0] or 0,
            "total_hits":    r[1] or 0,
            "last_hit":      str(r[2]) if r[2] else "Never",
            "last_stored":   str(r[3]) if r[3] else "Never"
        }
    except Exception as e:
        return {"error": str(e)}


def clear_cache() -> bool:
    """Clear all cached entries."""
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        cur.execute("TRUNCATE question_cache;")
        conn.commit()
        cur.close(); conn.close()
        print("🗑️ Cache cleared")
        return True
    except Exception as e:
        print(f"❌ Clear failed: {e}")
        return False