"""Tests for the Skills system (discovery, parsing, injection)."""
from __future__ import annotations

from pathlib import Path

from app.skills import (
    Skill,
    _parse_skill_md,
    discover_skills,
    load_skill_body,
    render_skills_for_prompt,
)


_SKILL_MD = """\
---
name: refactor
description: Safely refactor a function
triggers: refactor, restructure
---
When asked to refactor:
1. Read the target.
2. Plan with todo_write.
3. Make the change.
"""


class TestParse:
    def test_frontmatter_and_body(self):
        fm, body = _parse_skill_md(_SKILL_MD)
        assert fm["name"] == "refactor"
        assert fm["description"] == "Safely refactor a function"
        assert fm["triggers"] == ["refactor", "restructure"]
        assert "Read the target" in body

    def test_no_frontmatter(self):
        fm, body = _parse_skill_md("just body text")
        assert fm == {}
        assert "just body" in body

    def test_quoted_values(self):
        fm, _ = _parse_skill_md('---\nname: "x"\ndescription: "a, b"\n---\nbody')
        assert fm["name"] == "x"
        assert fm["description"] == "a, b"


class TestDiscover:
    def test_user_and_project_skills(self, tmp_path):
        # user skill
        user_dir = tmp_path / "user" / ".ye" / "skills"
        (user_dir / "alpha").mkdir(parents=True)
        (user_dir / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: user skill\n---\nbody-alpha", encoding="utf-8"
        )
        # project skill (overrides)
        proj_dir = tmp_path / "proj" / ".ye" / "skills"
        (proj_dir / "alpha").mkdir(parents=True)
        (proj_dir / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: project override\n---\nbody-proj", encoding="utf-8"
        )
        (proj_dir / "beta").mkdir(parents=True)
        (proj_dir / "beta" / "SKILL.md").write_text(
            "---\nname: beta\ndescription: only in project\n---\nbody-beta", encoding="utf-8"
        )
        import app.skills as skills_mod
        orig = skills_mod._USER_SKILLS_DIR
        skills_mod._USER_SKILLS_DIR = tmp_path / "user" / ".ye" / "skills"
        try:
            found = skills_mod.discover_skills(tmp_path / "proj")
        finally:
            skills_mod._USER_SKILLS_DIR = orig
        assert "alpha" in found and "beta" in found
        # project overrides user for same name
        assert found["alpha"].source == "project"
        assert found["alpha"].body == "body-proj"
        assert found["beta"].source == "project"


class TestRender:
    def test_empty_renders_nothing(self):
        assert render_skills_for_prompt({}) == ""

    def test_lists_skills(self):
        skills = {
            "refactor": Skill(name="refactor", description="Refactor code",
                              triggers=["refactor", "cleanup"]),
        }
        out = render_skills_for_prompt(skills)
        assert "/refactor" in out
        assert "Refactor code" in out
        assert "refactor" in out  # trigger shown


class TestLoadBody:
    def test_load_existing(self):
        skills = {"x": Skill(name="x", body="do the thing")}
        assert load_skill_body(skills, "x") == "do the thing"

    def test_load_missing_returns_none(self):
        assert load_skill_body({}, "nope") is None
