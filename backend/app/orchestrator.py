"""Agent Orchestrator — declarative plan routing for Ye's multi-agent system.

Article reference:
  "Harness 第一层 — Agent 出主意，Harness 拿决定"
  "Planner 可以提出计划，但 Orchestrator 必须裁决计划"
  "别让 Agent 开车，让 Agent 当导航"

Flow:
  User intent → Planner generates declarative plan
              → Orchestrator validates & routes each step
              → Each step assigned to appropriate agent
              → Orchestrator handles failures, retries, budget

Declarative plan format:
  {
    "steps": [
      {"step": 1, "intent": "research", "agent": "explore", "input": "..."},
      {"step": 2, "intent": "implement", "agent": "code", "input": "..."},
      {"step": 3, "intent": "review", "agent": "review", "input": "..."},
    ]
  }
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.llm.base_provider import ChatMessage


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    step: int
    intent: str  # "research", "implement", "review", "test", "summarize"
    agent: str   # "explore", "general", "plan", "review", "code"
    input: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    output: str = ""
    duration_ms: float = 0
    error: str = ""


@dataclass
class ExecutionPlan:
    """A declarative execution plan produced by Planner, managed by Orchestrator."""
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: float = 0
    status: str = "draft"  # draft → approved → running → completed/failed

    def get_step(self, step_num: int) -> PlanStep | None:
        for s in self.steps:
            if s.step == step_num:
                return s
        return None

    def next_pending(self) -> PlanStep | None:
        for s in self.steps:
            if s.status == PlanStepStatus.PENDING:
                return s
        return None

    def summary(self) -> str:
        lines = [f"Plan: {self.goal}", f"Status: {self.status}", ""]
        for s in self.steps:
            icon = {
                "pending": "[ ]", "running": "[~]", "completed": "[x]",
                "failed": "[!]", "skipped": "[-]",
            }.get(s.status.value, "[ ]")
            lines.append(f"  {icon} Step {s.step}: [{s.agent}] {s.intent} — {s.input[:60]}")
        return "\n".join(lines)


# Agent → allowed intents mapping
_AGENT_CAPABILITIES: dict[str, set[str]] = {
    "explore": {"research", "search", "analyze"},
    "plan": {"plan", "analyze", "design"},
    "review": {"review", "audit", "validate"},
    "code": {"implement", "fix", "refactor", "test"},
    "general": {"research", "implement", "fix", "test", "summarize", "analyze"},
}

# Common LLM mistakes for agent names → canonical names
_AGENT_ALIASES: dict[str, str] = {
    "researcher": "explore",
    "research": "explore",
    "analyst": "explore",
    "coder": "code",
    "developer": "code",
    "implementer": "code",
    "planner": "plan",
    "designer": "plan",
    "reviewer": "review",
    "auditor": "review",
}


def _extract_json(text: str) -> str | None:
    """Extract a JSON object from LLM output using balanced-brace matching.

    Tries in order:
      1. Direct parse of stripped text
      2. Extract from markdown code block (```json ... ```)
      3. Balanced brace scan — counts nesting depth, only accepts
         fully balanced candidates, tries each from longest to shortest
    """
    text = text.strip()

    # 1. Direct parse
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # 2. Markdown code block
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            candidate = parts[i]
            if candidate.startswith("json"):
                candidate = candidate[4:]
            candidate = candidate.strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                continue

    # 3. Balanced brace scan — find all top-level balanced {…}
    candidates: list[tuple[int, int]] = []
    starts: list[int] = []
    for i, ch in enumerate(text):
        if ch == "{":
            starts.append(i)
        elif ch == "}" and starts:
            open_pos = starts.pop()
            # Only keep top-level (no unmatched opens remaining)
            if not starts:
                candidates.append((open_pos, i + 1))

    # Try longest first — most likely to be the actual plan
    candidates.sort(key=lambda t: t[1] - t[0], reverse=True)
    for start, end in candidates:
        candidate = text[start:end]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue

    return None


def _validate_and_repair_plan(data: dict, user_input: str) -> list[dict] | None:
    """Validate and auto-repair a parsed plan dict. Returns repaired steps or None."""
    if not isinstance(data, dict):
        return None

    # Auto-wrap: single step without "steps" key
    if "steps" not in data and any(k in data for k in ("step", "intent", "agent", "input")):
        data = {"steps": [data]}

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None

    repaired = []
    for idx, sd in enumerate(raw_steps):
        if not isinstance(sd, dict):
            continue

        # Step number
        step_num = sd.get("step", idx + 1)
        try:
            step_num = int(step_num)
        except (ValueError, TypeError):
            step_num = idx + 1

        # Agent: remap aliases → canonical
        agent = str(sd.get("agent", "general")).lower().strip()
        agent = _AGENT_ALIASES.get(agent, agent)
        if agent not in _AGENT_CAPABILITIES:
            agent = "general"

        # Intent: if missing or invalid, pick first capability
        intent = str(sd.get("intent", "")).lower().strip()
        caps = _AGENT_CAPABILITIES[agent]
        if intent not in caps:
            intent = next(iter(caps))

        # Input
        inp = str(sd.get("input", "")).strip() or user_input

        repaired.append({
            "step": step_num,
            "intent": intent,
            "agent": agent,
            "input": inp,
        })

    return repaired if repaired else None


class Orchestrator:
    """Validates and executes declarative plans.

    The Orchestrator has three jobs:
      1. Validate: check that each step's agent has the right capabilities
      2. Route: assign each step to the correct agent with proper tools
      3. Handle failures: retry, skip, or abort based on failure type
    """

    def __init__(self, provider, model: str = "", budget=None, trace=None):
        self.provider = provider
        self.model = model
        self.budget = budget
        self.trace = trace

    def validate_plan(self, plan: ExecutionPlan) -> list[str]:
        """Validate a plan. Returns list of issues (empty = valid)."""
        issues = []
        for step in plan.steps:
            # Check agent exists
            if step.agent not in _AGENT_CAPABILITIES:
                issues.append(f"Step {step.step}: Unknown agent '{step.agent}'")
                continue
            # Check agent has capability for this intent
            caps = _AGENT_CAPABILITIES[step.agent]
            if step.intent not in caps:
                issues.append(
                    f"Step {step.step}: Agent '{step.agent}' cannot handle intent '{step.intent}' "
                    f"(capabilities: {', '.join(sorted(caps))})"
                )
        return issues

    async def generate_plan(self, user_input: str) -> ExecutionPlan:
        """Use the Planner Agent to generate a declarative plan from user input.

        Uses a 2-attempt strategy: on JSON parse failure, retries once with
        the model's own output and the error message so it can self-correct.
        Falls back to a single "general" step if both attempts fail.
        """
        plan_prompt = (
            "You are a task planner for an AI coding assistant. "
            "Given the user's request, break it down into a structured execution plan.\n\n"
            "Available agent types and their intents:\n"
            "  - explore: research, search, analyze\n"
            "  - plan: plan, analyze, design\n"
            "  - review: review, audit, validate\n"
            "  - code: implement, fix, refactor, test\n"
            "  - general: any intent (full capability)\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"steps": [{"step": 1, "intent": "...", "agent": "...", "input": "..."}, ...]}\n\n'
            "Rules:\n"
            "- Start with research/explore if the task involves unfamiliar code\n"
            "- End with review if the task modifies code\n"
            "- Use 'code' agent for implementation steps, not 'general'\n"
            "- Keep steps atomic — one clear goal per step\n"
            "- Maximum 6 steps\n\n"
            f"User request: {user_input}"
        )

        plan_text = ""
        last_error = ""

        for attempt in range(2):
            messages = [ChatMessage(role="system", content=plan_prompt)]
            if last_error and plan_text:
                # Retry: show the model its own failed output + error
                messages.append(ChatMessage(role="assistant", content=plan_text))
                messages.append(ChatMessage(
                    role="user",
                    content=(
                        f"Your previous response had a JSON error: {last_error}. "
                        "Please respond with ONLY the corrected JSON object."
                    ),
                ))
            else:
                messages.append(ChatMessage(role="user", content=user_input))

            plan_text = ""
            async for chunk in self.provider.chat(
                messages=messages, model=self.model, max_tokens=800, temperature=0.3,
            ):
                if chunk.type == "text_delta":
                    plan_text += chunk.text

            # Try to extract and repair JSON
            json_str = _extract_json(plan_text)
            if json_str is not None:
                try:
                    data = json.loads(json_str)
                    steps = _validate_and_repair_plan(data, user_input)
                    if steps:
                        plan = ExecutionPlan(goal=user_input)
                        for sd in steps:
                            plan.steps.append(PlanStep(**sd))
                        return plan
                    last_error = "Plan has no valid steps"
                except json.JSONDecodeError as e:
                    last_error = str(e)
            else:
                last_error = "No JSON object found in response"

        # Final fallback: single general step
        plan = ExecutionPlan(goal=user_input)
        plan.steps = [PlanStep(step=1, intent="general", agent="general", input=user_input)]
        return plan

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        cwd: str | None = None,
        on_step_start=None,
        on_step_end=None,
    ) -> ExecutionPlan:
        """Execute a validated plan step by step.

        Callbacks: on_step_start(step: PlanStep), on_step_end(step: PlanStep)
        """
        plan.status = "running"
        import os
        if cwd:
            os.chdir(cwd)

        for step in plan.steps:
            # Budget check before each step
            if self.budget and self.budget.should_stop():
                step.status = PlanStepStatus.SKIPPED
                step.error = "Budget exhausted"
                continue

            step.status = PlanStepStatus.RUNNING
            if on_step_start:
                on_step_start(step)

            start = asyncio.get_event_loop().time()
            try:
                result = await self._run_step(step, cwd)
                step.output = result
                step.status = PlanStepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = PlanStepStatus.FAILED
                # Decision: continue or abort?
                # For now, abort on failure (Harness decides, not Agent)
                plan.status = "failed"
                if on_step_end:
                    on_step_end(step)
                break

            step.duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            if on_step_end:
                on_step_end(step)

        if plan.status == "running":
            plan.status = "completed"

        return plan

    async def _run_step(self, step: PlanStep, cwd: str | None) -> str:
        """Execute a single plan step using the appropriate agent."""
        from app.agents import spawn_agent
        return await spawn_agent(
            task=step.input,
            provider=self.provider,
            model=self.model,
            cwd=cwd,
            agent_type=step.agent,
            max_iterations=8,
        )
