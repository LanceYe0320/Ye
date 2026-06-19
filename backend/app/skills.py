"""Skills system — reusable, shareable procedures (Claude Code-style).

A skill is a folder containing a SKILL.md with YAML-ish frontmatter:
    ---
    name: refactor
    description: Safely refactor a function with tests
    triggers: refactor, restructure, cleanup code
    ---
    <body: instructions injected into the conversation when the skill fires>

Skills live in two places (project skills override user skills of the same name):
  - project: <cwd>/.ye/skills/<name>/SKILL.md
  - user:    ~/.ye/skills/<name>/SKILL.md

Triggering:
  - Explicit: the user types `/<name>` — the skill body is appended as a user
    message so the agent follows it this turn.
  - Automatic: available skills are listed in the system prompt; if the user's
    message matches a trigger keyword, the skill is suggested/loaded. (We keep
    automatic loading conservative — inject the list and let the model decide,
    rather than keyword-matching ourselves, to avoid false positives.)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_USER_SKILLS_DIR = Path.home() / ".ye" / "skills"

_FRONTMATTER_RE = re.compile(
    r"^\s*---\s*\n(?P<fm>.*?)\n---\s*\n?(?P<body>.*)$", re.DOTALL,
)


@dataclass
class Skill:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    source: str = "user"   # "user" | "project"
    path: Path | None = None

    @property
    def trigger_summary(self) -> str:
        return ", ".join(self.triggers) if self.triggers else self.description


def _parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter_dict, body). Tolerant YAML-ish parse."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text.strip()
    fm: dict = {}
    for line in m.group("fm").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip().strip('"').strip("'")
            # triggers can be a comma list
            if k.strip() == "triggers":
                fm["triggers"] = [t.strip() for t in v.split(",") if t.strip()]
            else:
                fm[k.strip()] = v
    return fm, m.group("body").strip()


def _load_one(skill_md: Path, source: str) -> Skill | None:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except Exception:
        logger.debug("suppressed", exc_info=True)
        return None
    fm, body = _parse_skill_md(text)
    name = fm.get("name") or skill_md.parent.name
    return Skill(
        name=name,
        description=fm.get("description", ""),
        triggers=fm.get("triggers", []) if isinstance(fm.get("triggers"), list) else [],
        body=body,
        source=source,
        path=skill_md.parent,
    )


def discover_skills(cwd: Path | None = None) -> dict[str, Skill]:
    """Discover all skills (user + project). Returns {name: Skill}.

    Project skills (in <cwd>/.ye/skills) override user skills of the same name.
    """
    skills: dict[str, Skill] = {}
    # User skills first (lower precedence)
    if _USER_SKILLS_DIR.is_dir():
        for d in _USER_SKILLS_DIR.iterdir():
            md = d / "SKILL.md" if d.is_dir() else None
            if md and md.is_file():
                sk = _load_one(md, "user")
                if sk:
                    skills[sk.name] = sk
    # Project skills override
    if cwd is not None:
        proj_dir = cwd / ".ye" / "skills"
        if proj_dir.is_dir():
            for d in proj_dir.iterdir():
                md = d / "SKILL.md" if d.is_dir() else None
                if md and md.is_file():
                    sk = _load_one(md, "project")
                    if sk:
                        skills[sk.name] = sk
    return skills


def render_skills_for_prompt(skills: dict[str, Skill]) -> str:
    """Compact list of available skills for system-prompt injection.

    Lets the model decide when to suggest using one (conservative auto-trigger).
    """
    if not skills:
        return ""
    lines = ["\n\n## Available Skills (reusable procedures)"]
    lines.append("You can invoke a skill by describing it, or the user can type /<name>.")
    for sk in sorted(skills.values(), key=lambda s: s.name):
        trig = f" (triggers: {sk.trigger_summary})" if sk.triggers else ""
        lines.append(f"- /{sk.name}: {sk.description}{trig}")
    return "\n".join(lines)


def load_skill_body(skills: dict[str, Skill], name: str) -> str | None:
    """Return the body of a skill by name, or None if not found."""
    sk = skills.get(name)
    return sk.body if sk else None
