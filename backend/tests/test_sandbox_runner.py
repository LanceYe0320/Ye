"""Tests for the sandbox command runner.

Verifies the security-relevant behaviors: denied commands never execute,
API keys are stripped from the child environment, and timeouts are honored.
These run real subprocesses but only against trivial, safe commands.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from app.sandbox.runner import CommandResult, run_command, stream_command


def run(coro):
    """Run a coroutine to completion on a fresh loop (isolated per test)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestDeniedCommandsDoNotExecute:
    def test_non_allowlisted_returns_denied(self):
        res = run(run_command("curl http://evil.example.com"))
        assert res.exit_code == -1
        assert "denied" in res.stderr.lower() or "not in allowlist" in res.stderr.lower()

    def test_destructive_returns_denied(self):
        res = run(run_command("rm -rf /"))
        assert res.exit_code == -1
        assert res.stdout == ""

    def test_injection_returns_denied(self):
        res = run(run_command("echo $(whoami)"))
        assert res.exit_code == -1
        assert res.stdout == ""


class TestEnvSanitization:
    def test_api_key_stripped_from_child(self, monkeypatch):
        # If the key leaked into the child env, `env` could print it.
        monkeypatch.setenv("ZHIPU_API_KEY", "SECRET-LEAK-CHECK-123")
        monkeypatch.setenv("SECRET_KEY", "ANOTHER-SECRET-456")
        # Windows: `set VAR` prints it. POSIX: `echo $VAR`. Use python for both.
        res = run(run_command(
            "python -c \"import os; print(os.environ.get('ZHIPU_API_KEY','CLEAN'))\""
        ))
        assert res.exit_code == 0
        assert "SECRET-LEAK-CHECK-123" not in res.stdout
        assert "CLEAN" in res.stdout


class TestSuccessfulExecution:
    def test_echo_runs(self):
        res = run(run_command("echo hello-runner-test"))
        assert res.exit_code == 0
        assert "hello-runner-test" in res.stdout

    def test_custom_allowlist(self):
        # `ver`-like custom tool; use echo-style to stay cross-platform
        res = run(run_command(
            "python -c \"print('custom-ok')\"", custom_allowlist=[]
        ))
        assert res.exit_code == 0
        assert "custom-ok" in res.stdout


class TestTimeout:
    def test_command_times_out(self):
        # Sleep longer than the timeout. Use python -c for cross-platform sleep.
        res = run(run_command(
            "python -c \"import time; time.sleep(10)\"", timeout=1
        ))
        assert res.exit_code == -1
        assert "timed out" in res.stderr.lower()


class TestStreaming:
    def test_stream_yields_stdout_and_exit(self):
        outputs = []
        async def collect():
            async for chunk in stream_command("echo streamed-line"):
                outputs.append(chunk)
        run(collect())
        types = [o["type"] for o in outputs]
        assert "stdout" in types
        assert "exit" in types
        # the echoed line should appear in some stdout chunk
        joined = "".join(o.get("data", "") for o in outputs if o["type"] == "stdout")
        assert "streamed-line" in joined

    def test_stream_denied_yields_error(self):
        outputs = []
        async def collect():
            async for chunk in stream_command("rm -rf /"):
                outputs.append(chunk)
        run(collect())
        assert any(o["type"] == "error" for o in outputs)
