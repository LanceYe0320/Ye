from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str
    permissions: list[str] = field(default_factory=list)


@dataclass
class PluginTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[str]]
    required_permissions: list[str] = field(default_factory=list)


class PluginContext:
    def __init__(self, project_path: str):
        self.project_path = project_path

    async def read_file(self, path: str) -> str:
        from pathlib import Path
        target = Path(self.project_path) / path
        if not str(target.resolve()).startswith(str(Path(self.project_path).resolve())):
            raise PermissionError(f"Path traversal: {path}")
        return target.read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> str:
        from pathlib import Path
        target = Path(self.project_path) / path
        if not str(target.resolve()).startswith(str(Path(self.project_path).resolve())):
            raise PermissionError(f"Path traversal: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"

    async def run_command(self, command: str, timeout: int = 30) -> str:
        from app.sandbox.runner import run_command
        result = await run_command(command, cwd=self.project_path, timeout=timeout)
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output or "(no output)"


class BasePlugin(ABC):
    manifest: PluginManifest

    @abstractmethod
    async def on_activate(self, context: PluginContext) -> None:
        """Called when the plugin is activated."""
        ...

    @abstractmethod
    async def on_deactivate(self) -> None:
        """Called when the plugin is deactivated."""
        ...

    @abstractmethod
    def get_tools(self) -> list[PluginTool]:
        """Return the tools this plugin provides."""
        ...
