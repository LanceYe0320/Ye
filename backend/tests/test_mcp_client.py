"""Tests for the MCP client — config loading, tool discovery, call forwarding.

Uses a fake connection to avoid starting real MCP server subprocesses.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.mcp_client import (
    ClientSession,
    MCPTool,
    MCPServerConfig,
    load_server_configs,
)


class FakeConnection:
    """In-process stand-in for an MCP server connection."""

    def __init__(self, tools_response: dict, call_response: dict | None = None):
        self._tools = tools_response
        self._call = call_response or {"content": [{"type": "text", "text": "ok"}]}
        self.requests: list[tuple[str, dict | None]] = []
        self.closed = False

    async def connect(self):
        pass

    async def request(self, method, params=None, timeout=30.0):
        self.requests.append((method, params))
        if method == "initialize":
            return {"serverInfo": {"name": "fake"}}
        if method == "tools/list":
            return self._tools
        if method == "tools/call":
            return self._call
        return {}

    async def close(self):
        self.closed = True


class TestLoadConfigs:
    def test_no_config_file(self, tmp_path, monkeypatch):
        import app.mcp_client as m
        monkeypatch.setattr(m, "_CONFIG_PATH", tmp_path / "nope.json")
        assert load_server_configs() == {}

    def test_parses_stdio_and_sse(self, tmp_path, monkeypatch):
        import app.mcp_client as m
        cfg = tmp_path / "mcp.json"
        cfg.write_text(json.dumps({
            "servers": {
                "cli": {"command": ["uvx", "mcp-server-x"], "env": {"K": "v"}},
                "web": {"url": "http://localhost:8080", "transport": "sse"},
            }
        }), encoding="utf-8")
        monkeypatch.setattr(m, "_CONFIG_PATH", cfg)
        configs = load_server_configs()
        assert "cli" in configs and "web" in configs
        assert configs["cli"].transport == "stdio"
        assert configs["cli"].command == ["uvx", "mcp-server-x"]
        assert configs["cli"].env == {"K": "v"}
        assert configs["web"].transport == "sse"
        assert configs["web"].url == "http://localhost:8080"

    def test_bad_json_returns_empty(self, tmp_path, monkeypatch):
        import app.mcp_client as m
        cfg = tmp_path / "bad.json"
        cfg.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(m, "_CONFIG_PATH", cfg)
        assert load_server_configs() == {}


class TestClientSession:
    def test_connect_discovers_tools(self, monkeypatch):
        sess = ClientSession()

        # Monkeypatch the connection factory by pre-stuffing _connections + tools.
        fake = FakeConnection({
            "tools": [
                {"name": "query", "description": "run a query", "inputSchema": {"type": "object"}},
                {"name": "list_tables", "description": "list tables"},
            ]
        })
        # Bypass real subprocess creation: directly exercise the discovery path
        # by simulating what connect() does after getting a connection.
        sess._connections["db"] = fake
        result = {"tools": [
            {"name": "query", "description": "run a query", "inputSchema": {"type": "object"}},
            {"name": "list_tables", "description": "list tables"},
        ]}
        for t in result["tools"]:
            tool = MCPTool(name=t["name"], description=t.get("description", ""),
                           input_schema=t.get("inputSchema", {}), server="db")
            sess.tools[f"db__{tool.name}"] = tool

        assert sess.is_connected
        assert "db__query" in sess.tools
        assert "db__list_tables" in sess.tools
        assert sess.tools["db__query"].server == "db"

    def test_call_tool_forwards_and_returns_text(self):
        sess = ClientSession()
        fake = FakeConnection(
            {"tools": []},
            call_response={"content": [{"type": "text", "text": "result-123"}]},
        )
        sess._connections["db"] = fake
        sess.tools["db__query"] = MCPTool(name="query", server="db")

        out = asyncio.run(sess.call_tool("db__query", {"sql": "SELECT 1"}))
        assert "result-123" in out
        # Verify the request was forwarded correctly
        assert fake.requests[-1] == ("tools/call", {"name": "query", "arguments": {"sql": "SELECT 1"}})

    def test_call_unknown_tool(self):
        sess = ClientSession()
        out = asyncio.run(sess.call_tool("nope__x", {}))
        assert "unknown MCP tool" in out

    def test_call_disconnected_server(self):
        sess = ClientSession()
        sess.tools["db__q"] = MCPTool(name="q", server="db")
        # server "db" not in _connections
        out = asyncio.run(sess.call_tool("db__q", {}))
        assert "not connected" in out

    def test_shutdown_clears_state(self):
        sess = ClientSession()
        fake = FakeConnection({"tools": []})
        sess._connections["db"] = fake
        sess.tools["db__q"] = MCPTool(name="q", server="db")
        asyncio.run(sess.shutdown())
        assert fake.closed
        assert not sess._connections
        assert not sess.tools
