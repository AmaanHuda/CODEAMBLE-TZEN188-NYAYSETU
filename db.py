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
                    resolved BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """)
            # file_url/file_name/file_type/file_public_id hold Cloudinary's
            # response — Neon never stores the actual file bytes, only the link.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    file_url TEXT,
                    file_name TEXT,
                    file_type TEXT,
                    file_public_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_messages_case_id
                ON chat_messages (case_id, created_at);
                """)
            # CREATE TABLE IF NOT EXISTS is a no-op if the table already existed
            # from before these columns were added — patch them in explicitly so
            # deployments against an older schema self-heal on startup.
            cur.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_url TEXT;")
            cur.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_name TEXT;")
            cur.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_type TEXT;")
            cur.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_public_id TEXT;")
            cur.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS resolved BOOLEAN NOT NULL DEFAULT FALSE;")
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
                RETURNING id, user_id, category, summary, strength, resolved, created_at, updated_at;
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
                    SELECT id, user_id, category, summary, strength, resolved, created_at, updated_at
                    FROM cases WHERE id = %s AND user_id = %s;
                    """,
                    (case_id, user_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, user_id, category, summary, strength, resolved, created_at, updated_at
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


def mark_case_resolved(case_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE cases SET resolved = TRUE, updated_at = now()
                WHERE id = %s
                RETURNING id, user_id, category, summary, strength, resolved, created_at, updated_at;
                """,
                (case_id,),
            )
            case = cur.fetchone()
        conn.commit()
        return dict(case) if case else None


def list_cases_for_user(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, user_id, category, summary, strength, resolved, created_at, updated_at
                FROM cases WHERE user_id = %s ORDER BY updated_at DESC;
                """,
                (user_id,),
            )
            cases = cur.fetchall()
        return [dict(c) for c in cases]


# get_user_cases is what app.py's dashboard route calls — same query as
# list_cases_for_user, plus a human-friendly "updated_at_display" and a
# 0-3 "step" for the dashboard's progress timeline, computed here so
# app.py doesn't have to know about the raw timestamps.
def get_user_cases(user_id):
    cases = list_cases_for_user(user_id)
    for c in cases:
        c["updated_at_display"] = _time_ago(c["updated_at"])
        if c["resolved"]:
            c["step"] = 3
        elif c.get("summary"):
            c["step"] = 2
        elif c.get("category"):
            c["step"] = 1
        else:
            c["step"] = 0
    return cases


# --------------------------------------------------------------------------
# Chat messages
# --------------------------------------------------------------------------

def save_chat_message(case_id, role, content, file_url=None, file_name=None,
                       file_type=None, file_public_id=None):
    """
    file_url/file_public_id come straight from Cloudinary's upload response —
    the file itself lives on Cloudinary, only the reference is stored here.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO chat_messages (case_id, role, content, file_url, file_name, file_type, file_public_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, case_id, role, content, file_url, file_name, file_type, file_public_id, created_at;
                """,
                (case_id, role, content, file_url, file_name, file_type, file_public_id),
            )
            msg = cur.fetchone()
        conn.commit()
        return dict(msg)


def get_case_messages(case_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, case_id, role, content, file_url, file_name, file_type, file_public_id, created_at
                FROM chat_messages WHERE case_id = %s ORDER BY created_at ASC;
                """,
                (case_id,),
            )
            msgs = cur.fetchall()
        return [dict(m) for m in msgs]


# --------------------------------------------------------------------------
# Dashboard: documents + activity feed
# --------------------------------------------------------------------------

def get_user_documents(user_id):
    """Every chat message across the user's cases that has a file attached,
    newest first — powers the 'Recent documents' sidebar panel."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.file_name, m.file_url, m.file_public_id, m.case_id, m.created_at
                FROM chat_messages m
                JOIN cases c ON c.id = m.case_id
                WHERE c.user_id = %s AND m.file_url IS NOT NULL
                ORDER BY m.created_at DESC;
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["uploaded_at_display"] = _time_ago(d.pop("created_at"))
            d["size_display"] = ""  # Cloudinary's byte size isn't stored today
            out.append(d)
        return out


def get_recent_activity(user_id, limit=8):
    """Newest chat messages across all of the user's cases, formatted for
    the dashboard's activity feed."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.role, m.file_name, m.file_url, m.created_at
                FROM chat_messages m
                JOIN cases c ON c.id = m.case_id
                WHERE c.user_id = %s
                ORDER BY m.created_at DESC
                LIMIT %s;
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()

    out = []
    for r in rows:
        if r["file_url"]:
            icon, text = "📄", f"You uploaded {r['file_name'] or 'a document'}"
        elif r["role"] == "assistant":
            icon, text = "💬", "Received guidance on your case"
        else:
            icon, text = "📝", "You sent a message"
        out.append({"icon": icon, "text": text, "time": _time_ago(r["created_at"])})
    return out


def _time_ago(dt):
    """'2 days ago' / 'Today' style label for the dashboard."""
    from datetime import datetime, timezone

    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    days = delta.days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    weeks = days // 7
    return f"{weeks} week{'s' if weeks > 1 else ''} ago"