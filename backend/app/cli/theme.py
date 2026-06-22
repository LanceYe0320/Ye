"""Central visual theme for the Ye CLI.

One place to define colors, the logo, banners, and small render helpers so the
whole interface stays visually consistent. Keep this dependency-free (only Rich)
and import-cheap so it can be reused across the CLI.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Brand palette — a calm green/teal identity (the "leaf"), tuned for dark
# terminals but legible on light ones too.
# ---------------------------------------------------------------------------
PRIMARY = "#4ade80"        # bright leaf green — logo, key accents
PRIMARY_DEEP = "#22c55e"   # deeper green for borders
ACCENT = "#38bdf8"         # sky cyan — interactive hints, commands
ACCENT_SOFT = "#7dd3fc"    # lighter cyan
WARN = "#fbbf24"           # amber — warnings, plan mode
DANGER = "#f87171"         # soft red — errors, denied
SUCCESS = "#86efac"        # soft green — success, allow
MUTED = "#6b7280"          # gray — secondary text
MUTED_LIGHT = "#9ca3af"    # lighter gray

# Semantic styles used as Rich markup strings
S_PRIMARY = f"bold {PRIMARY}"
S_ACCENT = f"bold {ACCENT}"
S_MUTED = "dim"
S_DIM_GREEN = "dim green"
S_DIM_RED = "dim red"


# ---------------------------------------------------------------------------
# Brand mark — a tiny diamond/gem glyph used inline before the brand name.
# Unicode preferred (◆) with an ASCII fallback (<>) for legacy GBK consoles.
# Detected once via Rich's console capabilities.
# ---------------------------------------------------------------------------
def gem_glyph() -> str:
    """Return the best diamond glyph the current terminal can render.

    Uses ``sys.stdout.encoding`` directly (no Rich import) so the startup
    banner can render before Rich is loaded — saving ~190ms of import time.
    """
    import sys
    try:
        enc = (sys.stdout.encoding or "").lower().replace("-", "")
        if enc in ("utf8", "utf16", "utf32"):
            return "\u25C6"   # ◆ BLACK DIAMOND
    except Exception:
        pass
    return "<>"   # ASCII fallback


def render_logo_text():
    """Return a Rich Text object with a small colored gem mark."""
    from rich.text import Text
    t = Text()
    t.append(gem_glyph() + "\n", style=PRIMARY)
    return t


# ---------------------------------------------------------------------------
# Small reusable UI atoms
# ---------------------------------------------------------------------------

def info_panel(body, *, title: str | None = None, accent: str = ACCENT):
    """A soft, rounded panel with a thin colored title bar.

    `body` may be a string (Rich markup) or a Rich renderable.
    """
    from rich.panel import Panel
    return Panel(
        body,
        title=f"[{accent}] {title}[/{accent}]" if title else None,
        title_align="left",
        border_style=f"dim {accent}",
        padding=(0, 1),
        box=None,  # border-less, uses left rule feel via subtitle spacing
    )


def hint_bar(items: list[tuple[str, str]]) -> str:
    """Build a single-line hint strip from [(label, action), ...].

    e.g. hint_bar([("/help","commands"),("/model","switch")])
      → "[dim]tips:[/] [/cyan]/help[/] [dim]commands · [/cyan]/model[/] [dim]switch[/]"
    """
    parts = []
    for i, (label, action) in enumerate(items):
        parts.append(f"[{ACCENT}]{label}[/{ACCENT}]")
        parts.append(f"[{MUTED}] {action}[/{MUTED}]")
        if i < len(items) - 1:
            parts.append(f"[{MUTED}] · [/{MUTED}]")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tool-call render atoms. Used by both interactive and -p modes for a
# consistent look: a tinted arrow, the tool name, then a status mark.
# ---------------------------------------------------------------------------

# ANSI escape sequences (used in raw-stdout streaming paths where Rich markup
# can't easily be injected mid-line). All decorative characters are ASCII-safe
# so they render correctly in any terminal encoding (including GBK on Windows).
ANSI_DIM = "\x1b[2m"
ANSI_RESET = "\x1b[0m"
ANSI_GREEN = "\x1b[38;2;134;239;172m"   # SUCCESS
ANSI_RED = "\x1b[38;2;248;113;113m"     # DANGER
ANSI_ACCENT = "\x1b[38;2;56;189;248m"   # ACCENT cyan
ANSI_MUTED = "\x1b[38;2;107;114;128m"   # MUTED gray


def tool_start_line(name: str, progress: str = "") -> str:
    """Raw-stdout line shown when a tool starts executing."""
    tag = f" {progress}" if progress else ""
    # ASCII '>' branch glyph in accent, tool name in accent, leaves cursor
    # for the v/x status mark that follows on result.
    return f"  {ANSI_DIM}>{ANSI_RESET} {ANSI_ACCENT}{name}{ANSI_RESET}{ANSI_MUTED}{tag}{ANSI_RESET}  "


def tool_ok_line(elapsed: str, detail: str = "") -> str:
    """Raw-stdout tail shown when a tool succeeds."""
    if detail:
        return f"{ANSI_GREEN}v{ANSI_RESET} {ANSI_MUTED}{elapsed}{ANSI_RESET} {ANSI_DIM}{detail}{ANSI_RESET}"
    return f"{ANSI_GREEN}v{ANSI_RESET} {ANSI_MUTED}{elapsed}{ANSI_RESET}"


def tool_fail_line(elapsed: str = "") -> str:
    """Raw-stdout tail shown when a tool fails."""
    return f"{ANSI_RED}x{ANSI_RESET} {ANSI_MUTED}{elapsed}{ANSI_RESET}"

