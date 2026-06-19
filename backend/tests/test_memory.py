"""Tests for Memory enhanced retention scoring.

Covers:
  - Category weights
  - Keyword relevance scoring
  - Relationship bonus
  - Importance-based compression
  - Score clamping
"""

import time

from app.memory import (
    _CATEGORY_WEIGHTS,
    _compress_content,
    _extract_keywords,
    _STOP_WORDS,
    compute_retention_score,
)


class TestExtractKeywords:
    def test_english_keywords(self):
        kw = _extract_keywords("React hooks are important for state management")
        assert "react" in kw
        assert "hooks" in kw

    def test_stop_words_removed(self):
        kw = _extract_keywords("The and for are but not you")
        assert len(kw) == 0  # All are stop words

    def test_chinese_keywords(self):
        kw = _extract_keywords("React hooks 框架进行开发")
        assert "react" in kw


class TestCategoryWeights:
    def test_project_higher_than_reference(self):
        base = time.time() - 864000
        common = {"created_at": base, "access_count": 2, "last_access": time.time() - 259200, "size": 1000}

        meta_p = {"entries": {"t": {**common, "category": "project", "_keywords": ["x"]}}}
        meta_r = {"entries": {"t": {**common, "category": "reference", "_keywords": ["x"]}}}

        sp = compute_retention_score("t", meta_p)
        sr = compute_retention_score("t", meta_r)
        assert sp > sr, f"project ({sp}) should > reference ({sr})"

    def test_feedback_higher_than_user(self):
        base = time.time() - 864000
        common = {"created_at": base, "access_count": 2, "last_access": time.time() - 259200, "size": 1000}

        meta_f = {"entries": {"t": {**common, "category": "feedback", "_keywords": []}}}
        meta_u = {"entries": {"t": {**common, "category": "user", "_keywords": []}}}

        sf = compute_retention_score("t", meta_f)
        su = compute_retention_score("t", meta_u)
        assert sf > su, f"feedback ({sf}) should > user ({su})"


class TestKeywordRelevance:
    def test_matching_keywords_boost_score(self):
        base = time.time() - 864000
        common = {"created_at": base, "access_count": 2, "last_access": time.time() - 259200, "size": 1000}

        meta = {"entries": {"t": {**common, "category": "project", "_keywords": ["react", "hooks"]}}}
        score_no_kw = compute_retention_score("t", meta)
        score_with_kw = compute_retention_score("t", meta, context_keywords={"react", "hooks"})
        assert score_with_kw >= score_no_kw

    def test_non_matching_keywords_reduce_score(self):
        base = time.time() - 864000
        common = {"created_at": base, "access_count": 2, "last_access": time.time() - 259200, "size": 1000}

        meta = {"entries": {"t": {**common, "category": "project", "_keywords": ["react", "hooks"]}}}
        score_base = compute_retention_score("t", meta)
        score_no_match = compute_retention_score("t", meta, context_keywords={"python", "django"})
        assert score_no_match < score_base


class TestRelationshipBonus:
    def test_referenced_memories_score_higher(self):
        base = time.time() - 864000
        common = {"created_at": base, "access_count": 2, "last_access": time.time() - 259200, "size": 1000, "category": "project"}

        meta_base = {"entries": {"t": {**common, "_keywords": []}}}
        meta_refs = {"entries": {"t": {**common, "_keywords": [], "referenced_by": ["a", "b", "c"]}}}

        score_base = compute_retention_score("t", meta_base)
        score_refs = compute_retention_score("t", meta_refs)
        assert score_refs > score_base


class TestCompressContent:
    def test_short_content_unchanged(self):
        text = "Line one\nLine two"
        assert _compress_content(text) == text

    def test_selects_important_lines(self):
        content = "First topic line\nSecond plain line\nThird plain line\nImportant key metric: 42\nFifth plain line\nSixth plain line"
        result = _compress_content(content, max_lines=3)
        assert "First topic" in result
        assert "Important" in result

    def test_strips_headers(self):
        content = "---\nname: test\ncategory: project\ndate: 2026-01-01\n---\n\nReal content here\nMore content\nExtra content"
        result = _compress_content(content, max_lines=2)
        assert "---" not in result
        assert "name:" not in result


class TestScoreClamping:
    def test_score_always_in_range(self):
        old_meta = {"entries": {"old": {"created_at": 0, "access_count": 0, "last_access": 0, "size": 50000}}}
        score = compute_retention_score("old", old_meta)
        assert 0.0 <= score <= 1.0

    def test_fresh_frequently_accessed_scores_high(self):
        meta = {"entries": {"fresh": {
            "created_at": time.time(), "access_count": 20,
            "last_access": time.time(), "size": 100, "category": "project",
        }}}
        score = compute_retention_score("fresh", meta)
        assert score >= 0.8


class TestGetContextBatchIO:
    """Verify get_context batches meta read/write (no per-file disk churn)."""

    def test_get_context_records_access_batch(self, tmp_path, monkeypatch):
        # Point memory dir at a temp location and seed two memories + meta
        import app.memory as mem
        monkeypatch.setattr(mem, "_MEMORY_DIR", tmp_path)
        monkeypatch.setattr(mem, "_META_FILE", tmp_path / "_meta.json")
        monkeypatch.setattr(mem, "_CORE_MEMORY_FILE", tmp_path / "core.md")
        monkeypatch.setattr(mem, "_CORE_USER_FILE", tmp_path / "user.md")
        mem._memory_dir_cache = (0.0, [])
        (tmp_path / "proj_a.md").write_text("Project A details", encoding="utf-8")
        (tmp_path / "proj_b.md").write_text("Project B details", encoding="utf-8")

        # Count how many times _save_meta is called during ONE get_context
        save_count = {"n": 0}
        orig_save = mem._save_meta
        def counting_save(meta):
            save_count["n"] += 1
            orig_save(meta)
        monkeypatch.setattr(mem, "_save_meta", counting_save)

        mem.get_context(max_chars=4000)

        # Both memories accessed, but only ONE save (batched) — not two.
        meta = mem._load_meta()
        assert "proj_a" in meta["entries"]
        assert "proj_b" in meta["entries"]
        assert save_count["n"] == 1, f"expected 1 batched save, got {save_count['n']}"

    def test_list_memory_files_cached(self, tmp_path, monkeypatch):
        import app.memory as mem
        monkeypatch.setattr(mem, "_MEMORY_DIR", tmp_path)
        mem._memory_dir_cache = (0.0, [])
        (tmp_path / "a.md").write_text("x", encoding="utf-8")
        first = mem._list_memory_files()
        assert len(first) == 1
        # second call should hit cache (same mtime) — same list object
        second = mem._list_memory_files()
        assert second is first
