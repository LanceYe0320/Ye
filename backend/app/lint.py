"""Lightweight post-edit diagnostics — syntax error feedback without a full LSP.

opencode spins up real language servers (38 of them) and streams LSP
diagnostics back to the model after each edit. That's a big dependency for
a CLI tool. This module provides a pragmatic subset: it catches the
errors that actually block the agent's progress — syntax errors and
undefined-name issues — using tools that are either built-in or commonly
available, with zero required setup.

Detection per language:
  Python (.py)     py_compile (stdlib, always available) + optional pyflakes
  JavaScript (.js)  node --check (if node is on PATH)
  TypeScript (.ts)  tsc --noEmit (if tsc is on PATH) — optional
  JSON (.json)      json.loads (stdlib)
  Everything else   no diagnostics (returns empty)

The public surface is a single function, :func:`diagnose`, returning a
human-readable block the tool can append to its result so the model sees
"you just introduced a syntax error on line N" and fixes it in the next
loop iteration — closing the edit→error→re-edit loop that opencode's LSP
integration provides.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_ERRORS = 20


def _creation_flags() -> int:
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def _diagnose_python(path: Path) -> list[str]:
    """Python: py_compile for syntax + optional pyflakes for names."""
    errors: list[str] = []
    # 1. py_compile — catches syntax errors, always available (stdlib)
    try:
        import py_compile
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as e:
        # e.msg / e.exc_msg already include file:line detail
        msg = str(e).strip().splitlines()
        errors.extend(line for line in msg if line.strip())
    except Exception as e:
        errors.append(f"compile error: {e}")
    if errors:
        return errors[:_MAX_ERRORS]
    # 2. pyflakes — catches undefined names / unused imports (optional)
    try:
        result = subprocess.run(
            ["pyflakes", str(path)],
            capture_output=True, text=True, timeout=10,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0 and result.stdout.strip():
            errors.extend(
                line.strip() for line in result.stdout.splitlines() if line.strip()
            )
    except FileNotFoundError:
        pass  # pyflakes not installed — skip silently
    except Exception as e:
        logger.debug("pyflakes failed: %s", e)
    return errors[:_MAX_ERRORS]


def _diagnose_javascript(path: Path) -> list[str]:
    """JS: node --check (syntax only, fast, no execution)."""
    try:
        result = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True, text=True, timeout=10,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            return [line for line in err.splitlines() if line.strip()][:_MAX_ERRORS]
    except FileNotFoundError:
        pass  # node not installed
    except Exception as e:
        logger.debug("node check failed: %s", e)
    return []


def _diagnose_typescript(path: Path) -> list[str]:
    """TS: tsc --noEmit (optional, slow — only if installed)."""
    try:
        result = subprocess.run(
            ["tsc", "--noEmit", "--pretty", "false", str(path)],
            capture_output=True, text=True, timeout=20,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0 and result.stdout.strip():
            return [line.strip() for line in result.stdout.splitlines() if line.strip()][:_MAX_ERRORS]
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug("tsc check failed: %s", e)
    return []


def _diagnose_json(path: Path) -> list[str]:
    """JSON: json.loads (stdlib)."""
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"JSON error: {e}"]
    except Exception as e:
        return [f"read error: {e}"]
    return []


_DIAGNOSTORS = {
    ".py": _diagnose_python,
    ".js": _diagnose_javascript,
    ".mjs": _diagnose_javascript,
    ".cjs": _diagnose_javascript,
    ".ts": _diagnose_typescript,
    ".json": _diagnose_json,
}


def diagnose(file_path: str | Path) -> list[str]:
    """Return a list of diagnostic messages for ``file_path``.

    Empty list = no problems detected (or no diagnoser available for the
    file type). Messages are short, human-readable, and include line info
    where the underlying tool provides it.
    """
    p = Path(file_path)
    if not p.is_file():
        return []
    diagnoser = _DIAGNOSTORS.get(p.suffix.lower())
    if diagnoser is None:
        return []
    try:
        return diagnoser(p)
    except Exception as e:
        logger.debug("diagnose failed for %s: %s", p, e)
        return []


def diagnostic_block(file_path: str | Path) -> str:
    """Return a formatted diagnostics block, or "" if clean.

    The format mirrors opencode's LSP Diagnostic.report() so the agent sees
    a consistent "<diagnostics file=...>ERROR [line:col] msg</diagnostics>"
    structure it can act on.
    """
    errors = diagnose(file_path)
    if not errors:
        return ""
    fname = Path(file_path).name
    body = "\n".join(errors)
    return f'<diagnostics file="{fname}">\n{body}\n</diagnostics>'


__all__ = ["diagnose", "diagnostic_block"]
