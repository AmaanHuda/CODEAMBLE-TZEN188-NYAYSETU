import os

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

try:
    from dotenv import load_dotenv

    load_dotenv()  # reads a .env file in the project root, if present
except ImportError:
    pass  # falls back to whatever is already in the environment

# --------------------------------------------------------------------------
# Connection
#
# Set DATABASE_URL to your Neon connection string, e.g.:
#   postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
# (Neon gives you this exact string on the project's Connection Details page.)
#
# Easiest way: create a file named .env in the same folder as app.py containing:
#   DATABASE_URL=postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
# --------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Put your Neon connection string in the "
                "environment (or a .env file) before starting the app."
            )
        # sslmode/channel_binding are already in DATABASE_URL's query string —
        # don't pass them again as kwargs, or libpq errors on duplicate params.
        _pool = SimpleConnectionPool(1, 10, DATABASE_URL)
    return _pool


class get_conn:
    """Context manager: borrow a connection from the pool, always return it."""

    def __enter__(self):
        self.conn = get_pool().getconn()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.conn.rollback()
        get_pool().putconn(self.conn)


def init_db():
    """Create tables if they don't exist yet. Call once on startup."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cases (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    category TEXT,
                    summary TEXT,
                    strength INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_messages_case_id
                ON chat_messages (case_id, created_at);
                """)
        conn.commit()


def create_user(name, email, password_hash):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO users (name, email, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id, name, email, password_hash, created_at;
                """,
                (name, email, password_hash),
            )
            user = cur.fetchone()
        conn.commit()
        return dict(user)


def get_user_by_email(email):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, email, password_hash, created_at FROM users WHERE email = %s;",
                (email,),
            )
            user = cur.fetchone()
        return dict(user) if user else None


def get_user_by_id(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, email, password_hash, created_at FROM users WHERE id = %s;",
                (user_id,),
            )
            user = cur.fetchone()
        return dict(user) if user else None


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------

def create_case(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO cases (user_id)
                VALUES (%s)
                RETURNING id, user_id, category, summary, strength, created_at, updated_at;
                """,
                (user_id,),
            )
            case = cur.fetchone()
        conn.commit()
        return dict(case)


def get_case(case_id, user_id=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if user_id is not None:
                cur.execute(
                    """
                    SELECT id, user_id, category, summary, strength, created_at, updated_at
                    FROM cases WHERE id = %s AND user_id = %s;
                    """,
                    (case_id, user_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, user_id, category, summary, strength, created_at, updated_at
                    FROM cases WHERE id = %s;
                    """,
                    (case_id,),
                )
            case = cur.fetchone()
        return dict(case) if case else None


def update_case_meta(case_id, category=None, summary=None, strength=None):
    """Update whichever of category/summary/strength are provided (not None)."""
    fields, values = [], []
    if category is not None:
        fields.append("category = %s")
        values.append(category)
    if summary is not None:
        fields.append("summary = %s")
        values.append(summary)
    if strength is not None:
        fields.append("strength = %s")
        values.append(strength)
    if not fields:
        return
    fields.append("updated_at = now()")
    values.append(case_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE cases SET {', '.join(fields)} WHERE id = %s;",
                values,
            )
        conn.commit()


def list_cases_for_user(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, user_id, category, summary, strength, created_at, updated_at
                FROM cases WHERE user_id = %s ORDER BY updated_at DESC;
                """,
                (user_id,),
            )
            cases = cur.fetchall()
        return [dict(c) for c in cases]


# --------------------------------------------------------------------------
# Chat messages
# --------------------------------------------------------------------------

def save_chat_message(case_id, role, content):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO chat_messages (case_id, role, content)
                VALUES (%s, %s, %s)
                RETURNING id, case_id, role, content, created_at;
                """,
                (case_id, role, content),
            )
            msg = cur.fetchone()
        conn.commit()
        return dict(msg)


def get_case_messages(case_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, case_id, role, content, created_at
                FROM chat_messages WHERE case_id = %s ORDER BY created_at ASC;
                """,
                (case_id,),
            )
            msgs = cur.fetchall()
        return [dict(m) for m in msgs]