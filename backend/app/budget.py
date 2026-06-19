"""Token Budget — real-time cost control for Ye's agent loop.

Budget zones (NO model degradation — user chose glm-5.1 for a reason):
  GREEN:   Normal execution
  YELLOW:  Compress context, warn user
  RED:     Aggressive compression, strong warning
  BREAKER: Force stop, return partial result

"Agent 负责局部智能，Harness 负责全局控制。"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class BudgetZone(str, Enum):
    GREEN = "green"      # Normal
    YELLOW = "yellow"    # Compress context, warn
    RED = "red"          # Aggressive compression
    BREAKER = "breaker"  # Force stop


@dataclass
class BudgetConfig:
    """Configurable limits for token budget."""
    # Total token budget per task (0 = unlimited)
    max_total_tokens: int = 200_000
    # Per-step budget
    max_tokens_per_step: int = 20_000
    # Max tool calls in a single agentic loop
    max_tool_calls: int = 50
    # Max wall-clock time in seconds (0 = unlimited)
    max_duration_seconds: int = 1800  # 30 minutes
    # Yellow zone threshold (% of max_total_tokens)
    yellow_pct: float = 0.60
    # Red zone threshold (% of max_total_tokens)
    red_pct: float = 0.85
    # Breaker threshold (% of max_total_tokens)
    breaker_pct: float = 0.95
    # Enable/disable budget enforcement
    enabled: bool = True


@dataclass
class BudgetState:
    """Live budget tracking state."""
    total_tokens_used: int = 0
    prompt_tokens_used: int = 0
    completion_tokens_used: int = 0
    tool_call_count: int = 0
    step_count: int = 0
    start_time: float = field(default_factory=time.time)
    zone: BudgetZone = BudgetZone.GREEN
    warnings: list[str] = field(default_factory=list)
    circuit_broken: bool = False


class TokenBudget:
    """Real-time token budget tracker with zone-based control.

    Does NOT degrade model — keeps the user's chosen model throughout.
    Instead, controls cost by:
      - Compressing context when approaching limits
      - Warning the user at each zone transition
      - Force-stopping when budget is exhausted

    Usage:
        budget = TokenBudget(BudgetConfig(max_total_tokens=100_000))
        budget.start()

        budget.record_usage(prompt_tokens=500, completion_tokens=200)
        zone = budget.check_zone()
        if zone == BudgetZone.BREAKER:
            # Force stop
            ...
    """

    def __init__(self, config: BudgetConfig | None = None):
        self.config = config or BudgetConfig()
        self.state = BudgetState()

    def start(self):
        """Reset and start tracking."""
        self.state = BudgetState(start_time=time.time())

    def record_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0):
        """Record token usage from an API call."""
        self.state.total_tokens_used += prompt_tokens + completion_tokens
        self.state.prompt_tokens_used += prompt_tokens
        self.state.completion_tokens_used += completion_tokens
        self.state.step_count += 1

    def record_tool_call(self):
        """Record a tool invocation."""
        self.state.tool_call_count += 1

    def check_zone(self) -> BudgetZone:
        """Check current budget zone. Returns zone and updates state."""
        if not self.config.enabled:
            return BudgetZone.GREEN

        cfg = self.config
        st = self.state

        # Check hard limits first
        if cfg.max_tool_calls > 0 and st.tool_call_count >= cfg.max_tool_calls:
            st.zone = BudgetZone.BREAKER
            st.warnings.append(
                f"Tool call limit reached: {st.tool_call_count}/{cfg.max_tool_calls}"
            )
            st.circuit_broken = True
            return st.zone

        if cfg.max_duration_seconds > 0:
            elapsed = time.time() - st.start_time
            elapsed_pct = elapsed / cfg.max_duration_seconds
            if elapsed_pct >= 1.0:
                st.zone = BudgetZone.BREAKER
                elapsed_str = f"{elapsed:.0f}"
                st.warnings.append(
                    f"Duration limit reached: {elapsed_str}s/{cfg.max_duration_seconds}s"
                )
                st.circuit_broken = True
                return st.zone
            if elapsed_pct >= 0.8:
                st.zone = BudgetZone.RED
                st.warnings.append(
                    f"Duration approaching limit: {elapsed:.0f}s/{cfg.max_duration_seconds}s"
                )

        if cfg.max_total_tokens > 0:
            pct = st.total_tokens_used / cfg.max_total_tokens
            used_str = f"{st.total_tokens_used:,}"
            max_str = f"{cfg.max_total_tokens:,}"
            if pct >= cfg.breaker_pct:
                st.zone = BudgetZone.BREAKER
                st.warnings.append(
                    f"Token budget nearly exhausted: {used_str}/{max_str}"
                )
                st.circuit_broken = True
            elif pct >= cfg.red_pct:
                st.zone = BudgetZone.RED
                st.warnings.append(
                    f"Token budget critical: {used_str}/{max_str} — compressing context"
                )
            elif pct >= cfg.yellow_pct:
                st.zone = BudgetZone.YELLOW
                st.warnings.append(
                    f"Token budget warning: {used_str}/{max_str}"
                )
            else:
                st.zone = BudgetZone.GREEN

        return st.zone

    def should_stop(self) -> bool:
        """Whether the circuit breaker has been tripped."""
        return self.state.circuit_broken

    def get_status_text(self) -> str:
        """Human-readable budget status."""
        st = self.state
        cfg = self.config
        elapsed = time.time() - st.start_time
        mins, secs = divmod(int(elapsed), 60)

        used_str = f"{st.total_tokens_used:,}"
        max_str = f"{cfg.max_total_tokens:,}"

        lines = [
            f"  Zone: {st.zone.value}",
            f"  Tokens: {used_str} / {max_str}",
            f"  Steps: {st.step_count}",
            f"  Tool Calls: {st.tool_call_count}",
            f"  Duration: {mins}m {secs}s / {cfg.max_duration_seconds // 60}m",
        ]
        if st.warnings:
            lines.append(f"  Last Warning: {st.warnings[-1]}")

        return "\n".join(lines)
