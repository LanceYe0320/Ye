"""Session persistence for Ye CLI.


Sessions are saved as JSON files in ~/.ye/sessions/.
Each session stores messages, model, cwd, usage records, and timestamp.
"""

from __future__ import annotations
import logging

import json
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)
_SESSIONS_DIR = Path.home() / ".ye" / "sessions"
_CURRENT_SESSION_FILE = Path.home() / ".ye" / "current_session"


def _ensure_dir():
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_session(
    messages: list[dict],
    model: str,
    cwd: str,
    usage_records: list[dict] | None = None,
    session_id: str | None = None,
) -> str:
    """Save a session to disk. Returns the session ID."""
    _ensure_dir()
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = _SESSIONS_DIR / f"{session_id}.json"

    data = {
        "id": session_id,
        "model": model,
        "cwd": cwd,
        "messages": messages,
        "usage_records": usage_records or [],
        "saved_at": datetime.now().isoformat(),
        "message_count": len(messages),
    }
    filepath.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
        errors="surrogatepass",
    )

    # Update pointer to latest session
    _CURRENT_SESSION_FILE.write_text(session_id, encoding="utf-8")

    return session_id


def load_session(session_id: str | None = None) -> dict | None:
    """Load a session. If session_id is None, loads the most recent session."""
    _ensure_dir()

    if session_id is None:
        # Try current session pointer first
        if _CURRENT_SESSION_FILE.is_file():
            session_id = _CURRENT_SESSION_FILE.read_text(encoding="utf-8").strip()
        if not session_id:
            # Fallback: find most recent by filename
            sessions = sorted(_SESSIONS_DIR.glob("*.json"), reverse=True)
            if not sessions:
                return None
            session_id = sessions[0].stem

    filepath = _SESSIONS_DIR / f"{session_id}.json"
    if not filepath.is_file():
        return None

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return None
    return data


def list_sessions(limit: int = 10) -> list[dict]:
    """List recent sessions, newest first."""
    _ensure_dir()
    sessions = sorted(_SESSIONS_DIR.glob("*.json"), reverse=True)[:limit]
    results = []
    for fp in sessions:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            # Extract first user message as preview
            preview = ""
            for msg in data.get("messages", []):
                if msg.get("role") == "user" and msg.get("content"):
                    preview = msg["content"][:80]
                    break
            results.append({
                "id": data.get("id", fp.stem),
                "model": data.get("model", ""),
                "cwd": data.get("cwd", ""),
                "message_count": data.get("message_count", 0),
                "saved_at": data.get("saved_at", ""),
                "preview": preview,
            })
        except Exception:
            logger.debug("suppressed", exc_info=True)
            pass
    return results


def delete_session(session_id: str) -> bool:
    """Delete a session file."""
    filepath = _SESSIONS_DIR / f"{session_id}.json"
    if filepath.is_file():
        filepath.unlink()
        return True
    return False


# -- Serialization helpers for ChatMessage / ToolCall --

def serialize_messages(messages: list) -> list[dict]:
    """Convert ChatMessage objects to serializable dicts."""
    result = []
    for msg in messages:
        d: dict[str, Any] = {
            "role": msg.role,
            "content": msg.content or "",
        }
        if msg.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        result.append(d)
    return result


def deserialize_messages(messages_data: list[dict]) -> list:
    """Convert dicts back to ChatMessage objects (lazy import to avoid heavy loads)."""
    from app.llm.base_provider import ChatMessage, ToolCall

    result = []
    for d in messages_data:
        tool_calls = []
        for tc in d.get("tool_calls", []):
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=tc["name"],
                arguments=tc["arguments"],
            ))
        result.append(ChatMessage(
            role=d["role"],
            content=d.get("content", ""),
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
        ))
    return result


def serialize_usage_records(records: list) -> list[dict]:
    """Convert UsageRecord objects to dicts."""
    return [
        {"model": r.model, "prompt_tokens": r.prompt_tokens,
         "completion_tokens": r.completion_tokens, "total_tokens": r.total_tokens}
        for r in records
    ]


def deserialize_usage_records(records_data: list[dict]) -> list:
    """Convert dicts to UsageRecord objects."""
    from app.cli.main import UsageRecord
    return [
        UsageRecord(
            model=r["model"],
            prompt_tokens=r.get("prompt_tokens", 0),
            completion_tokens=r.get("completion_tokens", 0),
            total_tokens=r.get("total_tokens", 0),
        )
        for r in records_data
    ]
