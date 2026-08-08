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
    """Create the users table if it doesn't exist yet. Call once on startup."""
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
