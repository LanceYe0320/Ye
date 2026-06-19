"""MCP (Model Context Protocol) client — connect external tool servers.

Lets Ye use tools exposed by MCP servers (stdio subprocess or HTTP/SSE), the
same standard Claude Code uses to grow its tool ecosystem.

Config lives in ~/.ye/mcp_servers.json:
    {
      "servers": {
        "sqlite": {
          "command": ["uvx", "mcp-server-sqlite", "--db-path", "path.db"],
          "env": {}
        },
        "github": {
          "url": "http://localhost:8080",
          "transport": "sse"
        }
      }
    }

Lifecycle: ClientSession.connect() starts servers + discovers tools;
shutdown() closes them. Tools are exposed via session.tools (name→schema) and
session.call_tool(name, args).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".ye" / "mcp_servers.json"
_JSONRPC_VERSION = "2.0"


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    server: str = ""  # which server provides this


@dataclass
class MCPServerConfig:
    name: str
    command: list[str] = field(default_factory=list)   # stdio
    env: dict = field(default_factory=dict)
    url: str = ""                                        # sse/http
    transport: str = "stdio"                             # "stdio" | "sse"


def load_server_configs() -> dict[str, MCPServerConfig]:
    """Load MCP server configs from ~/.ye/mcp_servers.json."""
    if not _CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("suppressed", exc_info=True)
        return {}
    out: dict[str, MCPServerConfig] = {}
    for name, spec in (data.get("servers") or {}).items():
        spec = spec or {}
        transport = spec.get("transport") or ("sse" if spec.get("url") else "stdio")
        out[name] = MCPServerConfig(
            name=name,
            command=list(spec.get("command") or []),
            env=dict(spec.get("env") or {}),
            url=spec.get("url", ""),
            transport=transport,
        )
    return out


class _StdioConnection:
    """JSON-RPC over a subprocess stdin/stdout (newline-delimited JSON)."""

    def __init__(self, cfg: MCPServerConfig):
        self._cfg = cfg
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        env = dict(os.environ)
        env.update(self._cfg.env)
        self._proc = await asyncio.create_subprocess_exec(
            *self._cfg.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                mid = msg.get("id")
                if mid is not None and mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        if "error" in msg:
                            fut.set_exception(RuntimeError(str(msg["error"])))
                        else:
                            fut.set_result(msg.get("result"))
        except (asyncio.CancelledError, Exception):
            # Wake any waiters so they don't hang forever.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("MCP server closed"))
            self._pending.clear()

    async def request(self, method: str, params: dict | None = None, timeout: float = 30.0):
        assert self._proc and self._proc.stdin
        mid = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        payload = {"jsonrpc": _JSONRPC_VERSION, "id": mid, "method": method}
        if params is not None:
            payload["params"] = params
        self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(mid, None)
            raise

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass


class _SSEConnection:
    """JSON-RPC over HTTP POST (request/response), a simplified MCP HTTP transport."""

    def __init__(self, cfg: MCPServerConfig):
        self._cfg = cfg
        from app.llm.raw_http import AsyncClient
        self._http = AsyncClient(timeout=60.0, connect_timeout=15.0)
        self._next_id = 1

    async def connect(self) -> None:
        # No persistent handshake needed for the simple POST model.
        pass

    async def request(self, method: str, params: dict | None = None, timeout: float = 30.0):
        mid = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": _JSONRPC_VERSION, "id": mid, "method": method}
        if params is not None:
            payload["params"] = params
        body = json.dumps(payload).encode("utf-8")
        resp = await self._http.post(
            self._cfg.url.rstrip("/") + "/mcp",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        raw = await resp.read()
        try:
            msg = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MCP bad response: {e}") from e
        if "error" in msg:
            raise RuntimeError(str(msg["error"]))
        return msg.get("result")

    async def close(self) -> None:
        try:
            await self._http.aclose()
        except Exception:
            pass


class ClientSession:
    """Manages one or more MCP server connections + their tools."""

    def __init__(self):
        self._connections: dict[str, _StdioConnection | _SSEConnection] = {}
        self.tools: dict[str, MCPTool] = {}

    @property
    def is_connected(self) -> bool:
        return bool(self._connections)

    async def connect(self, configs: dict[str, MCPServerConfig] | None = None) -> None:
        """Start all configured servers and discover their tools.

        Servers that fail to start are logged and skipped (one bad server
        shouldn't break the whole agent).
        """
        configs = configs if configs is not None else load_server_configs()
        for name, cfg in configs.items():
            try:
                conn = _StdioConnection(cfg) if cfg.transport == "stdio" else _SSEConnection(cfg)
                await conn.connect()
                # MCP handshake: initialize, then list tools.
                await conn.request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ye", "version": "0.1.0"},
                }, timeout=20.0)
                result = await conn.request("tools/list", {}, timeout=20.0)
                self._connections[name] = conn
                for t in (result or {}).get("tools", []) if isinstance(result, dict) else []:
                    tool = MCPTool(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                        server=name,
                    )
                    if tool.name:
                        # Namespaced as server__tool to avoid collisions.
                        self.tools[f"{name}__{tool.name}"] = tool
                logger.info(f"MCP server '{name}': connected, {len([t for t in self.tools.values() if t.server==name])} tools")
            except Exception as e:
                logger.warning(f"MCP server '{name}' failed to connect: {e}")
                # Clean up the half-open connection.
                try:
                    if 'conn' in locals():
                        await conn.close()
                except Exception:
                    pass

    async def call_tool(self, namespaced_name: str, args: dict, timeout: float = 60.0) -> str:
        """Call a tool provided by an MCP server. Returns the text result."""
        tool = self.tools.get(namespaced_name)
        if tool is None:
            return f"Error: unknown MCP tool '{namespaced_name}'"
        conn = self._connections.get(tool.server)
        if conn is None:
            return f"Error: MCP server '{tool.server}' not connected"
        try:
            result = await conn.request(
                "tools/call",
                {"name": tool.name, "arguments": args},
                timeout=timeout,
            )
        except Exception as e:
            return f"Error calling MCP tool {namespaced_name}: {e}"
        # MCP returns content blocks; join their text.
        if isinstance(result, dict):
            content = result.get("content", [])
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
        return str(result)

    async def shutdown(self) -> None:
        """Close all server connections."""
        for conn in self._connections.values():
            try:
                await conn.close()
            except Exception:
                pass
        self._connections.clear()
        self.tools.clear()
