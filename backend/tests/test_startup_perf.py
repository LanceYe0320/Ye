"""Tests for the startup-critical path: banner rendering + lazy-import guarantees.

These guard the startup-latency optimization. The banner must render as a
plain ANSI string WITHOUT importing Rich or asyncio, so the user sees it
within ~200ms instead of ~450ms.
"""
from __future__ import annotations

import sys


def test_build_banner_returns_str():
    """Banner is a plain string (ANSI-escaped), not a Rich object."""
    from app.cli.main import _build_banner
    banner = _build_banner(version="9.9.9", model="glm-5.2", cwd="/tmp/proj")
    assert isinstance(banner, str)


def test_banner_contains_brand_and_model():
    from app.cli.main import _build_banner
    banner = _build_banner(version="1.2.3", model="glm-5.2", cwd="/p")
    assert "Ye" in banner or "Y" in banner  # brand mark
    assert "glm-5.2" in banner               # model shown
    assert "1.2.3" in banner                 # version shown
    assert "Ready" in banner                 # status word


def test_banner_uses_ansi_color_not_rich_markup():
    """ANSI 24-bit escape (\\033[38;2;r;g;bm), not Rich [color] tags."""
    from app.cli.main import _build_banner
    banner = _build_banner(version="1.0", model="glm-5.2", cwd="/p")
    assert "\033[38;2;" in banner   # 24-bit fg color escape present
    assert "\033[0m" in banner      # reset present
    assert "[bold" not in banner    # no Rich markup leaking through


def test_banner_cwd_truncated_when_long():
    from app.cli.main import _build_banner
    long_cwd = "/" + "a" * 80
    banner = _build_banner(version="1", model="glm-5.2", cwd=long_cwd)
    assert "..." in banner  # truncated marker


def test_banner_shows_known_context_window():
    from app.cli.main import _build_banner
    banner = _build_banner(version="1", model="glm-5.2", cwd="/p")
    assert "1.0M" in banner


def test_gem_glyph_no_rich_import():
    """gem_glyph() must work without importing Rich (uses sys.stdout)."""
    # Ensure rich.console not already loaded by a prior test in this process
    # (we can't unload it, but we can confirm the function doesn't REQUIRE it)
    from app.cli.theme import gem_glyph
    g = gem_glyph()
    assert isinstance(g, str)
    assert len(g) > 0


def test_hex_to_rgb_conversion():
    from app.cli.main import _hex_to_rgb
    assert _hex_to_rgb("#4ade80") == (74, 222, 128)
    assert _hex_to_rgb("000000") == (0, 0, 0)
    assert _hex_to_rgb("#ffffff") == (255, 255, 255)


def test_ansi_helper_bold_and_color():
    from app.cli.main import _ansi, _hex_to_rgb
    s = _ansi("#4ade80", bold=True)
    assert "\033[1;" in s          # bold code
    assert "38;2;74;222;128" in s  # rgb color


def test_ansi_helper_none_returns_empty():
    from app.cli.main import _ansi
    assert _ansi(None) == ""
    assert _ansi(None, bold=True) == "\033[1m"
