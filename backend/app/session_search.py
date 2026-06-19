"""Full-text search across past sessions using SQLite FTS5.


Inspired by Hermes Agent's session DB with FTS5 search.
Indexes all session messages, tool calls, and results for cross-session recall.

Tier 3 of the three-layer memory system.
"""
from __future__ import annotations
import logging

import json
import sqlite3
from pathlib import Path


logger = logging.getLogger(__name__)
_DB_PATH = Path.home() / ".ye" / "sessions.db"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS session_messages (
    session_id TEXT NOT NULL,
    msg_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_name TEXT,
    created_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS session_search USING fts5(
    session_id,
    content,
    tool_name,
    content='session_messages',
    content_rowid='rowid'
);

CREATE INDEX IF NOT EXISTS idx_session_id ON session_messages(session_id);
"""

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS sm_ai AFTER INSERT ON session_messages BEGIN
    INSERT INTO session_search(rowid, session_id, content, tool_name)
    VALUES (new.rowid, new.session_id, new.content, new.tool_name);
END;

CREATE TRIGGER IF NOT EXISTS sm_ad AFTER DELETE ON session_messages BEGIN
    INSERT INTO session_search(session_search, rowid, session_id, content, tool_name)
    VALUES ('delete', old.rowid, old.session_id, old.content, old.tool_name);
END;

CREATE TRIGGER IF NOT EXISTS sm_au AFTER UPDATE ON session_messages BEGIN
    INSERT INTO session_search(session_search, rowid, session_id, content, tool_name)
    VALUES ('delete', old.rowid, old.session_id, old.content, old.tool_name);
    INSERT INTO session_search(rowid, session_id, content, tool_name)
    VALUES (new.rowid, new.session_id, new.content, new.tool_name);
END;
"""


_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Return a module-level singleton connection, initializing the schema once.

    Previously this created a NEW connection and re-ran CREATE TABLE/TRIGGER
    scripts on every call — fixed overhead per /ss search and per index_session.
    Now the connection + schema are set up exactly once per process.
    """
    global _conn
    if _conn is not None:
        return _conn
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(_CREATE_TABLES)
    conn.executescript(_TRIGGERS)
    _conn = conn
    return conn


def index_session(session_id: str, messages: list[dict]) -> int:
    """Index all messages from a session into FTS5. Returns count indexed."""
    conn = _get_conn()
    # Remove old entries for this session
    conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id))

    # Build rows in memory, then executemany for a single bulk insert (much
    # faster than N round-trips for long sessions).
    rows = []
    for i, msg in enumerate(messages):
        content = msg.get("content", "") or ""
        tool_name = ""
        for tc in msg.get("tool_calls", []):
            tool_name = tc.get("name", "")
            content += " " + json.dumps(tc.get("arguments", {}), ensure_ascii=False)

        if not content.strip():
            continue
        rows.append((session_id, i, msg.get("role", ""), content, tool_name))

    if rows:
        conn.executemany(
            "INSERT INTO session_messages (session_id, msg_index, role, content, tool_name) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    conn.commit()
    return len(rows)


def search_sessions(query: str, limit: int = 10) -> list[dict]:
    """Full-text search across all indexed sessions. Returns matching snippets."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                sm.session_id,
                sm.role,
                snippet(session_search, 2, '>>>', '<<<', '...', 20) as snippet,
                sm.tool_name,
                sm.msg_index
            FROM session_search ss
            JOIN session_messages sm ON ss.rowid = sm.rowid
            WHERE session_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results = []
    for row in rows:
        sid, role, snippet, tool_name, idx = row
        results.append({
            "session_id": sid,
            "role": role,
            "snippet": snippet,
            "tool_name": tool_name or "",
            "msg_index": idx,
        })
    return results


def format_search_results(results: list[dict]) -> str:
    """Format search results for display."""
    if not results:
        return "No matching sessions found."

    lines = []
    current_session = ""
    for r in results:
        if r["session_id"] != current_session:
            current_session = r["session_id"]
            lines.append(f"\n## Session: {current_session}")
        tool = f" [{r['tool_name']}]" if r["tool_name"] else ""
        lines.append(f"  {r['role']}{tool}: {r['snippet']}")
    return "\n".join(lines)


def search_as_context(query: str, max_chars: int = 2000) -> str:
    """Search and return results formatted for system prompt injection."""
    results = search_sessions(query, limit=5)
    if not results:
        return ""
    text = format_search_results(results)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"
    return f"## Session Search Results for '{query}'\n{text}"


def rebuild_index():
    """Rebuild the FTS index from session JSON files on disk."""
    from app.sessions import _SESSIONS_DIR

    conn = _get_conn()
    conn.execute("DELETE FROM session_messages")
    conn.commit()

    count = 0
    for fp in _SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("suppressed", exc_info=True)
            pass
            continue
        sid = data.get("id", fp.stem)
        messages = data.get("messages", [])
        count += index_session(sid, messages)

    return f"Rebuilt index: {count} messages from {len(list(_SESSIONS_DIR.glob('*.json')))} sessions"
