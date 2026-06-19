"""Persistent cron scheduler for Ye CLI.


Inspired by Hermes Agent's cron system — define scheduled tasks in natural language,
persisted to ~/.ye/crons.json.

Jobs have: id, schedule (cron expression or natural lang), prompt, last_run, enabled.
"""
from __future__ import annotations
import logging

import json
import time
import uuid
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)
_CRON_FILE = Path.home() / ".ye" / "crons.json"

_PRESETS: dict[str, str] = {
    "every minute": "* * * * *",
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
    "nightly": "0 2 * * *",
}


def _load_crons() -> list[dict]:
    if _CRON_FILE.is_file():
        try:
            return json.loads(_CRON_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("suppressed", exc_info=True)
            pass
    return []


def _save_crons(crons: list[dict]):
    _CRON_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CRON_FILE.write_text(json.dumps(crons, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_schedule(schedule: str) -> str:
    """Convert natural language to cron expression, or pass through."""
    lower = schedule.lower().strip()
    if lower in _PRESETS:
        return _PRESETS[lower]
    # Already a 5-field cron expression
    parts = schedule.split()
    if len(parts) == 5:
        return schedule
    return schedule


def create_job(prompt: str, schedule: str, name: str = "") -> dict:
    """Create a new cron job. Returns the job dict."""
    crons = _load_crons()
    job = {
        "id": uuid.uuid4().hex[:8],
        "name": name or f"cron-{len(crons) + 1}",
        "schedule": _parse_schedule(schedule),
        "schedule_raw": schedule,
        "prompt": prompt,
        "enabled": True,
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "run_count": 0,
    }
    crons.append(job)
    _save_crons(crons)
    return job


def list_jobs(enabled_only: bool = False) -> list[dict]:
    """List all cron jobs."""
    crons = _load_crons()
    if enabled_only:
        return [j for j in crons if j.get("enabled", True)]
    return crons


def get_job(job_id: str) -> dict | None:
    """Get a job by ID."""
    for j in _load_crons():
        if j["id"] == job_id:
            return j
    return None


def update_job(job_id: str, **updates) -> dict | None:
    """Update a cron job's fields. Returns the updated job or None."""
    crons = _load_crons()
    for j in crons:
        if j["id"] == job_id:
            if "schedule" in updates:
                updates["schedule"] = _parse_schedule(updates["schedule"])
            j.update(updates)
            _save_crons(crons)
            return j
    return None


def delete_job(job_id: str) -> bool:
    """Delete a cron job by ID."""
    crons = _load_crons()
    before = len(crons)
    crons = [j for j in crons if j["id"] != job_id]
    if len(crons) < before:
        _save_crons(crons)
        return True
    return False


def mark_run(job_id: str) -> None:
    """Record that a job was just executed."""
    crons = _load_crons()
    for j in crons:
        if j["id"] == job_id:
            j["last_run"] = datetime.now().isoformat()
            j["run_count"] = j.get("run_count", 0) + 1
            break
    _save_crons(crons)


def toggle_job(job_id: str) -> dict | None:
    """Toggle a job's enabled state."""
    crons = _load_crons()
    for j in crons:
        if j["id"] == job_id:
            j["enabled"] = not j.get("enabled", True)
            _save_crons(crons)
            return j
    return None


def format_jobs_table() -> str:
    """Pretty-print all cron jobs."""
    crons = _load_crons()
    if not crons:
        return "No cron jobs. Use /cron create to add one."

    lines = ["Cron Jobs:", f"  {'ID':8s} {'Name':20s} {'Schedule':16s} {'Runs':>4s} {'Status':8s}", "  " + "-" * 64]
    for j in crons:
        status = "ON" if j.get("enabled", True) else "OFF"
        runs = str(j.get("run_count", 0))
        last = j.get("last_run", "never")
        if last and last != "never":
            last = last[:16]
        lines.append(
            f"  {j['id']:8s} {j.get('name', ''):20s} {j.get('schedule', ''):16s} "
            f"{runs:>4s} {status:8s}"
        )
        lines.append(f"  {'':8s} Prompt: {j.get('prompt', '')[:60]}")
        lines.append(f"  {'':8s} Last: {last}")
    return "\n".join(lines)
