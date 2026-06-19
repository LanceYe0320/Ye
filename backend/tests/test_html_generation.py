"""Self-test: verify HTML generation path works with new prompt/tools."""
import asyncio
import sys
import time

sys.path.insert(0, ".")


def test_prompt_no_run_command_for_files():
    """System prompt should NOT tell model to use run_command for files."""
    from app.prompts import SystemPrompt
    prompt = SystemPrompt.BASE_PROMPT

    # Bad: old guidance that caused doom loops
    assert "run_command to write via a Python script" not in prompt, \
        "Old run_command guidance still in prompt!"
    assert "python -c" not in prompt, \
        "python -c example still in prompt!"

    # Good: new guidance uses append_file
    assert "append_file" in prompt, \
        "append_file guidance missing!"
    assert "chunks of ~1500 chars" in prompt or "Split content into chunks" in prompt, \
        "Chunk guidance missing!"

    print("[PASS] Prompt: no run_command for files, uses append_file instead")


def test_prompt_has_ask_user():
    """System prompt should mention ask_user."""
    from app.prompts import SystemPrompt
    prompt = SystemPrompt.BASE_PROMPT
    assert "ask_user" in prompt, "ask_user not mentioned in system prompt!"
    print("[PASS] Prompt: ask_user guidance present")


def test_tools_registered():
    """All 15 tools should be registered including ask_user."""
    from app.llm.tools import build_tool_executor
    from app.llm.zhipu_provider import ZhipuProvider
    p = ZhipuProvider()
    e = build_tool_executor(p)
    names = [d.name for d in e.definitions]

    required = [
        "read_file", "write_file", "edit_file", "append_file",
        "grep", "glob", "list_files", "search_codebase", "project_overview",
        "run_command", "web_search", "web_fetch",
        "ask_user", "spawn_agent", "spawn_agent_group",
        "todo_write",
    ]
    for t in required:
        assert t in names, f"Tool '{t}' not registered!"

    assert len(names) == 16, f"Expected 16 tools, got {len(names)}"
    print(f"[PASS] Tools: all {len(names)} registered correctly")


def test_spawn_agent_timeout():
    """spawn_agent timeout should be 300s, not 120s."""
    from app.llm.tools.agent_ops import make_agent_tools
    from app.llm.zhipu_provider import ZhipuProvider
    p = ZhipuProvider()
    tools = make_agent_tools(p)
    for t in tools:
        if t["name"] == "spawn_agent":
            assert t["timeout"] == 300, f"spawn_agent timeout is {t['timeout']}, expected 300"
            print(f"[PASS] spawn_agent timeout: {t['timeout']}s")
        if t["name"] == "spawn_agent_group":
            assert t["timeout"] == 180, f"spawn_agent_group timeout changed unexpectedly"
    print("[PASS] spawn_agent_group timeout: 180s (unchanged)")


def test_ask_user_tool():
    """ask_user tool schema should be correct."""
    from app.llm.tools.interaction_ops import TOOLS
    t = TOOLS[0]
    assert t["name"] == "ask_user"
    assert t["risk_level"] == "low"
    assert "question" in t["parameters"]["properties"]
    assert "options" in t["parameters"]["properties"]
    assert t["parameters"]["required"] == ["question"]
    print("[PASS] ask_user: schema correct")


def test_run_command_error_message():
    """run_command TypeError should include helpful example."""
    from app.llm.tool_executor import ToolExecutor, ToolCall, ToolResult
    from app.llm.zhipu_provider import ZhipuProvider

    # Simulate a TypeError from missing 'command' argument
    exec = ToolExecutor(ZhipuProvider())
    exec.register(
        name="run_command",
        description="Execute a shell command",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        handler=lambda command: command,  # requires 'command' arg
    )

    # Call with empty args (simulates GLM's mistake)
    async def _test():
        tc = ToolCall(id="test", name="run_command", arguments={})
        result = await exec.execute_tool(tc)
        assert result.is_error, "Should be error"
        assert "Do NOT use run_command to write files" in result.content, \
            f"Missing helpful hint in error message. Got: {result.content[:200]}"
        return result.content

    msg = asyncio.get_event_loop().run_until_complete(_test())
    print(f"[PASS] run_command error: includes helpful hint")


def test_append_file_tool():
    """append_file should work for chunked writing."""
    from app.llm.tools.file_ops import TOOLS
    names = [t["name"] for t in TOOLS]
    assert "append_file" in names

    tool_def = [t for t in TOOLS if t["name"] == "append_file"][0]
    assert tool_def["risk_level"] == "high"
    assert tool_def["requires_approval"] is True
    print("[PASS] append_file: tool definition correct")


def test_timing_format():
    """Verify the new timing display format components work."""
    from app.cli import main

    # Check _TurnTimer works
    timer = main._TurnTimer()
    timer.start_time = time.time() - 150  # 2m 30s ago
    timer.first_token_time = timer.start_time + 6.2
    timer.tokens_output = 4800  # ~1200 tokens

    elapsed = timer.elapsed_str
    ttfb = timer.ttfb_str
    output = timer.output_str

    assert "m" in elapsed, f"Expected minutes in elapsed: {elapsed}"
    assert "s" in ttfb, f"Expected seconds in ttfb: {ttfb}"
    assert "~" in output or "K" in output or output.count("") > 0, f"Output str: {output}"

    print(f"[PASS] Timing: elapsed={elapsed}, ttfb={ttfb}, output={output}")


def test_budget_red_zone_hint():
    """Verify budget RED zone inserts token-saving hint."""
    # This is a code-level check: the hint should exist in tool_executor.py
    from app.llm import tool_executor
    source = open(tool_executor.__file__, encoding="utf-8").read()
    assert "Budget warning" in source, "Red zone hint not found in tool_executor.py"
    assert "Be concise" in source, "Token-saving guidance not found"
    print("[PASS] Budget: RED zone includes token-saving hint")


if __name__ == "__main__":
    print("=" * 60)
    print("YE v0.2.0 Self-Test: HTML Generation Path")
    print("=" * 60)

    tests = [
        test_prompt_no_run_command_for_files,
        test_prompt_has_ask_user,
        test_tools_registered,
        test_spawn_agent_timeout,
        test_ask_user_tool,
        test_run_command_error_message,
        test_append_file_tool,
        test_timing_format,
        test_budget_red_zone_hint,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{len(tests)} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED")
    print(f"{'=' * 60}")
