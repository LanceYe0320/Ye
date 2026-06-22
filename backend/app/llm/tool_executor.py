"""Enhanced Tool Executor — Ye's agentic loop with full Harness integration.

Implements:
  - Budget-driven zone control (GREEN → YELLOW → RED → BREAKER)
  - Failure Handler with real strategy execution (retry/abort/escalate)
  - Doom Loop detection (consecutive same-tool calls)
  - Concurrent tool execution for independent calls
  - Execution Trace (structured JSONL observability)
  - Tool Registry integration (risk_level, permissions, rate limits)
  - Auto context compression when budget enters YELLOW/RED

"Agent 负责局部智能，Harness 负责全局控制。"
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable

from app.llm.base_provider import (
    BaseLLMProvider,
    ChatMessage,
    StreamingChunk,
    ToolAbortError,
    ToolCall,
    ToolDefinition,
    ToolEscalationError,
    ToolResult,
)

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[str]]

# Max consecutive calls to the SAME tool+args before doom-loop kicks in.
# Tuned between opencode's strict 3 and the original 8: Chinese LLMs (GLM,
# DeepSeek) sometimes need a couple of legitimate retries, but 8 let real
# loops burn through budget. 4 catches stuck loops fast while tolerating
# one or two honest retries.
_DOOM_LOOP_THRESHOLD = 4
# Public alias (tests / external code may import this name)
DOOM_LOOP_THRESHOLD = _DOOM_LOOP_THRESHOLD
# Max consecutive calls to the same tool NAME (any args) for non-exempt tools.
_DOOM_LOOP_NAME_THRESHOLD = 6
# Read-only tools exempt from doom loop — reading many files is normal exploration
_DOOM_LOOP_EXEMPT = {"read_file", "grep", "glob", "list_files", "search_codebase", "append_file", "project_overview"}

# Max chars of tool result to keep in LLM context (prevents context explosion)
_CONTEXT_TOOL_RESULT_LIMIT = 3000
# Tools whose results should be truncated for context (read-only exploration tools)
_TRUNCATE_TOOLS = {"read_file", "list_files", "list_directory", "glob", "search_codebase"}


def _truncate_for_context(tool_name: str, content: str) -> str:
    """Truncate tool result for LLM context to prevent context explosion.

    Keeps head + tail with a truncation marker in the middle.
    Display remains unaffected (uses full content).
    """
    if tool_name not in _TRUNCATE_TOOLS:
        return content
    if len(content) <= _CONTEXT_TOOL_RESULT_LIMIT:
        return content
    head = _CONTEXT_TOOL_RESULT_LIMIT * 2 // 3
    tail = _CONTEXT_TOOL_RESULT_LIMIT // 3
    return (
        content[:head]
        + f"\n\n... [truncated {len(content) - head - tail:,} chars, use read_file with offset/limit to see more] ...\n\n"
        + content[-tail:]
    )


class ToolExecutor:
    """Agentic loop executor with Harness controls.

    The Agent (LLM) decides *what* to do.
    The Harness (this class) decides *whether it's allowed*.
    """

    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider
        self._handlers: dict[str, ToolHandler] = {}
        self._definitions: list[ToolDefinition] = []
        self._timeouts: dict[str, int] = {}

        # Harness components (set externally via setters)
        self._budget = None
        self._trace = None
        self._failure_handler = None
        self._tool_registry = None

        # Doom-loop tracking
        self._recent_tool_names: list[str] = []

        # Callback: called when budget zone requires context compression
        # Signature: async (zone: str, messages: list[ChatMessage]) -> list[ChatMessage]
        self._on_compact_needed: Callable | None = None

        # Callback: called for user approval of dangerous tools
        # Signature: async (tool_name: str, args: dict) -> bool
        # Returns True to allow, False to deny.
        self._on_approval_needed: Callable | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        risk_level: str = "medium",
        allowed_agents: list[str] | None = None,
        requires_approval: bool = False,
        audit: bool = True,
        timeout: int = 30,
        **kwargs,
    ):
        """Register a tool with handler + governance metadata.

        If a ToolRegistry has been attached (via set_tool_registry / set_registry),
        the tool is also registered there so governance metadata (risk level,
        allowed agents, etc.) is queryable through the registry.
        """
        self._handlers[name] = handler
        self._timeouts[name] = timeout
        self._definitions.append(
            ToolDefinition(name=name, description=description, parameters=parameters)
        )
        # Mirror into the registry if one is attached
        if self._tool_registry is not None:
            try:
                self._tool_registry.register(
                    name=name,
                    description=description,
                    parameters=parameters,
                    handler=handler,
                    risk_level=risk_level,
                    allowed_agents=allowed_agents,
                    requires_approval=requires_approval,
                    audit=audit,
                    timeout=timeout,
                    **kwargs,
                )
            except Exception:
                logger.debug("suppressed error", exc_info=True)

    @property
    def definitions(self) -> list[ToolDefinition]:
        return self._definitions

    # ------------------------------------------------------------------
    # Harness setters
    # ------------------------------------------------------------------

    def set_budget(self, budget):
        self._budget = budget

    def set_trace(self, trace):
        self._trace = trace

    def set_failure_handler(self, handler):
        self._failure_handler = handler

    def set_tool_registry(self, registry):
        self._tool_registry = registry

    # Alias for the public name expected by tests / external callers
    set_registry = set_tool_registry

    def set_compact_callback(self, callback: Callable):
        """Set callback for auto context compression.

        callback signature: async (zone: str, messages: list[ChatMessage])
                            -> list[ChatMessage]
        Called when budget zone is YELLOW or RED.
        """
        self._on_compact_needed = callback

    def set_approval_callback(self, callback: Callable):
        """Set callback for user approval of dangerous tools.

        callback signature: async (tool_name: str, args: dict) -> bool
        Returns True to allow execution, False to deny.
        """
        self._on_approval_needed = callback

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call with timeout and error handling."""
        handler = self._handlers.get(tool_call.name)
        if not handler:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Unknown tool: {tool_call.name}",
                is_error=True,
            )

        # Get timeout: prefer executor's stored timeout, fallback to registry
        timeout_seconds = self._timeouts.get(tool_call.name, 30)
        if self._tool_registry is not None:
            spec = self._tool_registry.get(tool_call.name)
            if spec is not None and spec.timeout > timeout_seconds:
                timeout_seconds = spec.timeout

        try:
            result = await asyncio.wait_for(
                handler(**tool_call.arguments),
                timeout=timeout_seconds,
            )
            return ToolResult(tool_call_id=tool_call.id, content=result)
        except TypeError as e:
            # Model passed wrong arguments — give helpful feedback for self-correction
            import inspect
            sig = inspect.signature(handler)
            expected = list(sig.parameters.keys())
            received = list(tool_call.arguments.keys())
            # Build a concrete example to help the model self-correct
            example = ""
            if tool_call.name == "run_command":
                example = (
                    "\nExample: {\"command\": \"ls -la\"} or {\"command\": \"pip install requests\"}.\n"
                    "Do NOT use run_command to write files — use write_file or append_file instead."
                )
            return ToolResult(
                tool_call_id=tool_call.id,
                content=(
                    f"Tool '{tool_call.name}' called with wrong arguments: {e}. "
                    f"Expected: {expected}. Received: {received}.{example}"
                ),
                is_error=True,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Tool '{tool_call.name}' timed out after {timeout_seconds}s",
                is_error=True,
            )
        except Exception as e:
            logger.error(f"Tool execution error ({tool_call.name}): {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Error: {e}",
                is_error=True,
            )

    async def _execute_single_tool(
        self,
        tc: ToolCall,
        current_messages: list[ChatMessage],
        agent_role: str = "general",
    ) -> tuple[ToolResult, float]:
        """Execute one tool call with full Harness checks.

        Returns (result, duration_ms).
        Raises ToolAbortError / ToolEscalationError on ABORT/ESCALATE strategy.
        """
        # --- Trace: tool call ---
        if self._trace is not None:
            risk = "medium"
            if self._tool_registry is not None:
                spec = self._tool_registry.get(tc.name)
                if spec is not None:
                    risk = spec.risk_level.value
            self._trace.tool_call(tc.name, tc.arguments, risk=risk)

        # --- Permission check ---
        if self._tool_registry is not None:
            perm = self._tool_registry.check_permission(tc.name, agent_role)
            if not perm["allowed"]:
                if self._trace is not None:
                    self._trace.tool_result(tc.name, perm["reason"], 0, blocked=True)
                return ToolResult(
                    tool_call_id=tc.id,
                    content=f"Permission denied: {perm['reason']}",
                    is_error=True,
                ), 0

        # --- Operation-level permission (triplet ruleset) ---
        # This is DISTINCT from the role-based check above: check_permission()
        # gates which agent ROLES may use a tool at all (allow/deny). This
        # triplet ruleset gates specific OPERATIONS by (tool, pattern) and
        # adds the "ask" tier for interactive approval. They compose:
        # role check first (hard gate), then operation check (soft gate).
        # Falls back to the legacy coarse tool-name map if the ruleset
        # module is unavailable.
        try:
            from app.permission_rules import check_tool as _check_rules
            _perm_result = _check_rules(tc.name, **tc.arguments)
        except Exception:
            try:
                from app.permissions import check_tool as _check_perm
                _perm_result = _check_perm(tc.name)
            except Exception:
                _perm_result = "ask"
        if _perm_result == "deny":
            return ToolResult(
                tool_call_id=tc.id,
                content=f"Tool '{tc.name}' is denied by permission rules.",
                is_error=True,
            ), 0
        if _perm_result == "ask" and self._on_approval_needed is not None:
            approved = await self._on_approval_needed(tc.name, tc.arguments)
            if not approved:
                return ToolResult(
                    tool_call_id=tc.id,
                    content=f"User denied execution of {tc.name}.",
                    is_error=True,
                ), 0

        start = time.time()
        result = await self.execute_tool(tc)
        duration_ms = (time.time() - start) * 1000

        # --- Tool-call repair: salvage malformed calls from GLM/DeepSeek ---
        # When the first execution fails AND we haven't already retried the
        # repaired version, attempt a deterministic repair (snake_case→camel,
        # alias fix, edit_file slot swap, glob normalization) and re-run once.
        if result.is_error and not getattr(tc, "_repaired", False):
            try:
                from app.llm.tool_repair import repair_tool_call
                known_names = [d.name for d in self._definitions]
                repaired = repair_tool_call(tc, known_names)
            except Exception:
                repaired = None
            if repaired is not None and (repaired.name != tc.name or repaired.arguments != tc.arguments):
                # Re-route through the full executor path so permission /
                # approval / trace still apply to the repaired call.
                logger.info("Attempting repaired tool call: %s", repaired.name)
                # Mark so we don't recurse forever on the repaired call.
                # ToolCall is a plain dataclass, so a plain attr set is fine
                # (kept under a sentinel name to avoid colliding with real fields).
                repaired._repaired = True  # type: ignore[attr-defined]
                return await self._execute_single_tool(
                    repaired, current_messages, agent_role
                )

        # --- Failure Handler: classify and EXECUTE strategy ---
        if result.is_error and self._failure_handler is not None:
            from app.failure import FailureAction
            action = self._failure_handler.handle(tc.name, result.content)
            if self._trace is not None:
                self._trace.error("tool_failure", f"{tc.name}: {result.content[:100]} [action: {action.value}]")

            if action == FailureAction.ABORT:
                raise ToolAbortError(tc.name, result.content)

            elif action == FailureAction.ESCALATE:
                raise ToolEscalationError(tc.name, result.content)

            elif action == FailureAction.RETRY_FIX_ARGS:
                # Don't retry with the same broken args — return error to the
                # model so it can self-correct in the next agentic loop iteration.
                pass

            elif action == FailureAction.RETRY:
                # Transient error (timeout, rate limit) — retry same call after backoff
                key = f"{tc.name}:{self._failure_handler.classify(tc.name, result.content).value}"
                retries = self._failure_handler.get_retry_count(key)
                if retries <= self._failure_handler.max_retries:
                    backoff = min(2 ** retries, 8)
                    await asyncio.sleep(backoff)
                    return await self._execute_single_tool(tc, current_messages, agent_role)

            # SKIP / FALLBACK / DEGRADE / RETRY_FIX_ARGS: return error result, let the LLM decide

        # --- Trace: tool result ---
        if self._trace is not None:
            self._trace.tool_result(tc.name, result.content, duration_ms)

        # --- Budget: record tool call ---
        if self._budget is not None:
            self._budget.record_tool_call()

        return result, duration_ms

    async def _execute_tools_concurrent(
        self,
        tool_calls: list[ToolCall],
        current_messages: list[ChatMessage],
        agent_role: str = "general",
    ) -> AsyncIterator[StreamingChunk]:
        """Execute independent tool calls concurrently for speed.

        Tool calls are independent if they target different tools or different files.
        Same-file writes are serialized to avoid race conditions.
        """
        if len(tool_calls) <= 1:
            # Single call — no concurrency needed
            for tc in tool_calls:
                try:
                    result, duration_ms = await self._execute_single_tool(
                        tc, current_messages, agent_role
                    )
                except ToolAbortError:
                    raise
                except ToolEscalationError:
                    raise

                current_messages.append(
                    ChatMessage(
                        role="tool",
                        content=_truncate_for_context(tc.name, result.content),
                        tool_call_id=tc.id,
                    )
                )
                if result.is_error:
                    yield StreamingChunk(
                        type="tool_execution_error",
                        text=result.content[:500],
                        tool_call_id=tc.id,
                    )
                else:
                    yield StreamingChunk(
                        type="tool_execution_result",
                        text=result.content[:2000],
                        tool_call_id=tc.id,
                    )
            return

        # Check for same-file conflicts (writes to same path)
        _SAFE_CONCURRENT = {"read_file", "search_files", "list_directory", "grep", "glob", "list_files", "search_codebase", "project_overview"}
        can_parallel = all(tc.name in _SAFE_CONCURRENT for tc in tool_calls)

        if can_parallel:
            tasks = []
            for tc in tool_calls:
                tasks.append(self._execute_single_tool(tc, current_messages, agent_role))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for tc, res in zip(tool_calls, results):
                if isinstance(res, ToolAbortError):
                    raise res
                if isinstance(res, ToolEscalationError):
                    raise res
                if isinstance(res, Exception):
                    current_messages.append(
                        ChatMessage(
                            role="tool",
                            content=f"Error: {res}",
                            tool_call_id=tc.id,
                        )
                    )
                    yield StreamingChunk(
                        type="tool_execution_error",
                        text=str(res)[:500],
                        tool_call_id=tc.id,
                    )
                else:
                    result, duration_ms = res
                    current_messages.append(
                        ChatMessage(
                            role="tool",
                            content=_truncate_for_context(tc.name, result.content),
                            tool_call_id=tc.id,
                        )
                    )
                    if result.is_error:
                        yield StreamingChunk(
                            type="tool_execution_error",
                            text=result.content[:500],
                            tool_call_id=tc.id,
                        )
                    else:
                        yield StreamingChunk(
                            type="tool_execution_result",
                            text=result.content[:2000],
                            tool_call_id=tc.id,
                        )
        else:
            # Serial execution for potentially conflicting tools
            for tc in tool_calls:
                try:
                    result, duration_ms = await self._execute_single_tool(
                        tc, current_messages, agent_role
                    )
                except ToolAbortError:
                    raise
                except ToolEscalationError:
                    raise

                current_messages.append(
                    ChatMessage(
                        role="tool",
                        content=_truncate_for_context(tc.name, result.content),
                        tool_call_id=tc.id,
                    )
                )
                if result.is_error:
                    yield StreamingChunk(
                        type="tool_execution_error",
                        text=result.content[:500],
                        tool_call_id=tc.id,
                    )
                else:
                    yield StreamingChunk(
                        type="tool_execution_result",
                        text=result.content[:2000],
                        tool_call_id=tc.id,
                    )

    # ------------------------------------------------------------------
    # Doom Loop Detection
    # ------------------------------------------------------------------

    @property
    def _registry(self):
        """Backwards-compat alias for the attached ToolRegistry."""
        return self._tool_registry

    def _truncate_for_model(self, content: str, tool_name: str = "read_file") -> str:
        """Truncate a tool result string for inclusion in the LLM context.

        Thin wrapper over the module-level _truncate_for_context() so callers
        (and tests) can use an instance method.
        """
        return _truncate_for_context(tool_name, content)

    def _check_doom_loop(self, tool_calls: list) -> str | None:
        """Detect consecutive calls to the same tool with same args (doom loop).

        Read-only tools (read_file, grep, glob, etc.) are exempt — reading
        many different files is normal exploration, not a doom loop.

        Accepts either a list of ToolCall objects (the live loop path) or a
        pre-built list of (name, args_str) tuples (used by tests), so callers
        can supply a history directly without going through the loop.
        """
        import json as _json

        # Normalize input into (name, args_key) pairs.
        # Two supported shapes:
        #   - ToolCall objects (.name, .arguments)
        #   - (name, args_str_or_dict) tuples
        normalized: list[tuple[str, str]] = []
        for item in tool_calls:
            if isinstance(item, tuple) and len(item) == 2:
                name, args = item
                if isinstance(args, str):
                    args_key = args[:200]
                else:
                    args_key = _json.dumps(args, sort_keys=True, default=str)[:200]
                normalized.append((str(name), args_key))
            elif hasattr(item, "name"):
                args = getattr(item, "arguments", {})
                if isinstance(args, str):
                    args_key = args[:200]
                else:
                    args_key = _json.dumps(args, sort_keys=True, default=str)[:200]
                normalized.append((str(item.name), args_key))

        # Accumulate into rolling history (live loop path relies on this)
        self._recent_tool_names.extend(normalized)
        max_history = _DOOM_LOOP_THRESHOLD * 2
        if len(self._recent_tool_names) > max_history:
            self._recent_tool_names = self._recent_tool_names[-max_history:]

        # If callers passed a ready-made history, evaluate against that;
        # otherwise evaluate against the accumulated rolling history.
        candidate = normalized if normalized else self._recent_tool_names

        # Rule 1 (strongest): the EXACT same (tool, args) repeated N times is a
        # doom loop regardless of whether the tool is exempt — re-reading the
        # same file identically is just as stuck as rewriting it.
        if len(candidate) >= _DOOM_LOOP_THRESHOLD:
            last_n = candidate[-_DOOM_LOOP_THRESHOLD:]
            if len(set(last_n)) == 1:
                return last_n[0][0]

        # Rule 2: for NON-exempt tools, also flag the same tool name called
        # many times even with differing args. Two sub-rules:
        #   (a) same tool NAME (any args) _DOOM_LOOP_THRESHOLD times in a row,
        #   (b) same tool NAME _DOOM_LOOP_NAME_THRESHOLD times within the
        #       recent window (looser — catches slow drift loops).
        non_exempt_history = [
            (n, a) for n, a in candidate if n not in _DOOM_LOOP_EXEMPT
        ]
        if len(non_exempt_history) >= _DOOM_LOOP_THRESHOLD:
            last_n = non_exempt_history[-_DOOM_LOOP_THRESHOLD:]
            if len(set(n for n, _ in last_n)) == 1:
                return last_n[0][0]

            tool_names_only = [name for name, _ in non_exempt_history[-_DOOM_LOOP_NAME_THRESHOLD:]]
            if len(tool_names_only) >= _DOOM_LOOP_NAME_THRESHOLD and len(set(tool_names_only)) == 1:
                return tool_names_only[0]

        return None

    # ------------------------------------------------------------------
    # Auto Context Compression
    # ------------------------------------------------------------------

    async def _maybe_compact_context(
        self,
        zone,
        current_messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """Trigger context compression when budget zone requires it.

        YELLOW: suggest compression (compress older messages)
        RED:    force compression (aggressive, keep only recent)
        """
        if self._on_compact_needed is None:
            return current_messages

        if zone.value in ("yellow", "red"):
            try:
                compressed = await self._on_compact_needed(zone.value, current_messages)
                return compressed
            except Exception as e:
                logger.warning(f"Context compression failed: {e}")
                return current_messages

        return current_messages

    # ------------------------------------------------------------------
    # Main Agentic Loop
    # ------------------------------------------------------------------

    async def run_agentic_loop(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        max_iterations: int = 50,
        agent_role: str = "general",
    ) -> AsyncIterator[StreamingChunk]:
        """Run the agentic loop with full Harness controls.

        Yields StreamingChunk for each event (text, tool calls, usage, etc.).
        The loop continues until the LLM stops requesting tool calls
        or a Harness control triggers termination.
        """
        current_messages = list(messages)
        self._recent_tool_names.clear()

        try:
            for iteration in range(max_iterations):
                pending_tool_calls: list[ToolCall] = []
                assistant_parts: list[str] = []

                # --- Budget: check zone ---
                effective_model = model
                if self._budget is not None:
                    zone = self._budget.check_zone()

                    if self._trace is not None and zone.value != "green":
                        self._trace.budget_event(
                            zone.value,
                            self._budget.state.total_tokens_used,
                        )

                    # BREAKER: force stop
                    if self._budget.should_stop():
                        yield StreamingChunk(
                            type="text_delta",
                            text=f"\n[Budget circuit breaker: "
                                 f"{self._budget.state.warnings[-1] if self._budget.state.warnings else 'limit reached'}]",
                        )
                        current_messages.append(
                            ChatMessage(role="assistant", content="[Budget circuit breaker triggered]")
                        )
                        yield StreamingChunk(
                            type="messages_update",
                            text="",
                            usage={"messages": current_messages},
                        )
                        if self._trace is not None:
                            self._trace.circuit_break("budget_exhausted")
                            self._trace.finish("[Budget circuit breaker]", success=False)
                        return

                    # YELLOW: warn only. RED: compress if context is actually large.
                    if zone.value == "yellow":
                        pass
                    elif zone.value == "red":
                        total_chars = sum(len(m.content or "") for m in current_messages)
                        if total_chars > 30000:
                            current_messages = await self._maybe_compact_context(
                                zone, current_messages
                            )
                            yield StreamingChunk(
                                type="budget_compact",
                                text=f"[Context auto-compressed due to budget zone: {zone.value}]",
                            )
                        # Inject a hint to the model to be more efficient
                        yield StreamingChunk(
                            type="text_delta",
                            text=(
                                f"\n[Budget warning: {self._budget.state.total_tokens_used:,}"
                                f"/{self._budget.config.max_total_tokens:,} tokens used. "
                                f"Be concise — avoid reading large files or repeating failed approaches.]\n"
                            ),
                        )

                # --- Trace: step start ---
                budget_zone = "green"
                if self._budget is not None:
                    budget_zone = self._budget.check_zone().value
                if self._trace is not None:
                    self._trace.step_start(iteration + 1, effective_model or "", budget_zone)

                # --- Call LLM ---
                async for chunk in self.provider.chat(
                    messages=current_messages,
                    tools=self._definitions if self._definitions else None,
                    model=effective_model,
                ):
                    if chunk.type == "text_delta":
                        yield chunk
                        assistant_parts.append(chunk.text)

                    elif chunk.type == "usage":
                        # Record usage in budget
                        if self._budget is not None:
                            self._budget.record_usage(
                                prompt_tokens=chunk.usage.get("prompt_tokens", 0),
                                completion_tokens=chunk.usage.get("completion_tokens", 0),
                            )
                        yield chunk  # Also yield for caller to track

                    elif chunk.type == "tool_call_end":
                        try:
                            args = json.loads(chunk.tool_call_arguments)
                        except json.JSONDecodeError:
                            # Log when GLM sends empty/malformed arguments
                            logger.warning(
                                f"Tool '{chunk.tool_call_name}': failed to parse arguments "
                                f"(len={len(chunk.tool_call_arguments)}). "
                                f"Raw: {chunk.tool_call_arguments[:200]}"
                            )
                            args = {}
                        pending_tool_calls.append(
                            ToolCall(
                                id=chunk.tool_call_id,
                                name=chunk.tool_call_name,
                                arguments=args,
                            )
                        )
                        yield chunk

                    elif chunk.type == "done":
                        if not pending_tool_calls:
                            # No tool calls — LLM is done, emit final messages update
                            final_text = "".join(assistant_parts)
                            current_messages.append(
                                ChatMessage(role="assistant", content=final_text)
                            )
                            if self._trace is not None:
                                self._trace.step_end(iteration + 1, False, len(final_text))
                                self._trace.finish(final_text, success=True)
                            yield StreamingChunk(
                                type="messages_update",
                                text="",
                                usage={"messages": current_messages},
                            )
                            return

                        # --- Doom Loop Detection ---
                        doom_tool = self._check_doom_loop(pending_tool_calls)
                        if doom_tool is not None:
                            if self._trace is not None:
                                self._trace.doom_loop(doom_tool, _DOOM_LOOP_THRESHOLD)
                            # Inject a warning message instead of executing the loop
                            warning = (
                                f"[Doom Loop Detected: '{doom_tool}' called "
                                f"{_DOOM_LOOP_THRESHOLD}+ times consecutively. "
                                f"Breaking the loop — try a different approach.]"
                            )
                            yield StreamingChunk(type="text_delta", text=warning)
                            current_messages.append(
                                ChatMessage(role="assistant", content=warning)
                            )
                            # Add a user-perspective hint to break the loop
                            current_messages.append(
                                ChatMessage(
                                    role="user",
                                    content=f"The tool '{doom_tool}' keeps returning the same result. "
                                            f"Please try a completely different approach.",
                                )
                            )
                            if self._trace is not None:
                                self._trace.step_end(iteration + 1, True, len(warning))
                            # Continue the loop — the LLM will see the hint
                            pending_tool_calls.clear()
                            continue

                        # --- Build assistant message with tool calls ---
                        assistant_msg = ChatMessage(
                            role="assistant",
                            content="".join(assistant_parts),
                            tool_calls=pending_tool_calls,
                        )
                        current_messages.append(assistant_msg)

                        if self._trace is not None:
                            self._trace.step_end(
                                iteration + 1, True, len("".join(assistant_parts))
                            )

                        # --- Yield tool execution start events ---
                        _SAFE_CONCURRENT = {"read_file", "search_files", "list_directory", "grep", "glob", "list_files", "search_codebase"}
                        can_parallel = all(tc.name in _SAFE_CONCURRENT for tc in pending_tool_calls)
                        if can_parallel and len(pending_tool_calls) > 1:
                            # Group concurrent tools into one summary event
                            tool_names = [tc.name for tc in pending_tool_calls]
                            unique = sorted(set(tool_names))
                            if len(unique) == 1:
                                summary = f"Executing: {unique[0]} ×{len(pending_tool_calls)}"
                            else:
                                parts = [f"{n}×{c}" if c > 1 else n for n, c in sorted((n, tool_names.count(n)) for n in unique)]
                                summary = f"Executing: {', '.join(parts)}"
                            yield StreamingChunk(
                                type="tool_execution_start",
                                text=summary,
                                tool_call_id="",
                            )
                        else:
                            for tc in pending_tool_calls:
                                yield StreamingChunk(
                                    type="tool_execution_start",
                                    text=f"Executing: {tc.name}",
                                    tool_call_id=tc.id,
                                )

                        # --- Execute tools (concurrent when safe) ---
                        async for chunk in self._execute_tools_concurrent(
                            pending_tool_calls, current_messages, agent_role
                        ):
                            yield chunk

                        # Clear for next iteration
                        pending_tool_calls = []

                    elif chunk.type == "error":
                        if self._trace is not None:
                            self._trace.error("provider_error", chunk.text)
                        yield chunk
                        yield StreamingChunk(
                            type="messages_update",
                            text="",
                            usage={"messages": current_messages},
                        )
                        return

        except ToolAbortError as e:
            if self._trace is not None:
                self._trace.error("abort", str(e))
            yield StreamingChunk(
                type="text_delta",
                text=f"\n[Task aborted: {e}]",
            )
            yield StreamingChunk(
                type="messages_update",
                text="",
                usage={"messages": current_messages},
            )
            if self._trace is not None:
                self._trace.finish(f"[Aborted: {e}]", success=False)
            return

        except ToolEscalationError as e:
            if self._trace is not None:
                self._trace.error("escalation", str(e))
            yield StreamingChunk(
                type="escalation",
                text=f"[Needs human intervention: {e}]",
            )
            yield StreamingChunk(
                type="messages_update",
                text="",
                usage={"messages": current_messages},
            )
            if self._trace is not None:
                self._trace.finish(f"[Escalated: {e}]", success=False)
            return

        # --- Hard termination: max iterations reached ---
        final_text = (
            f"[Reached maximum of {max_iterations} tool iterations. "
            f"This is a very high limit — the task may be stuck in a loop "
            f"or not fully complete.]"
        )
        yield StreamingChunk(type="text_delta", text=final_text)
        current_messages.append(ChatMessage(role="assistant", content=final_text))
        yield StreamingChunk(
            type="messages_update",
            text="",
            usage={"messages": current_messages},
        )
        if self._trace is not None:
            self._trace.finish(final_text, success=False)
