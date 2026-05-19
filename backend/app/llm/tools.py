from pathlib import Path

from app.indexer.vector_store import search_code
from app.llm.tool_executor import ToolExecutor
from app.llm.zhipu_provider import ZhipuProvider
from app.sandbox.runner import run_command


async def _read_file_handler(path: str) -> str:
    p = Path(path).resolve()
    if not p.is_file():
        return f"Error: File not found: {path}"
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"


async def _write_file_handler(path: str, content: str) -> str:
    p = Path(path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} bytes to {path}"


async def _run_command_handler(command: str, timeout: int = 60) -> str:
    result = await run_command(command, timeout=timeout)
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    if result.exit_code != 0:
        output += f"\n[exit code: {result.exit_code}]"
    return output or "(no output)"


async def _list_files_handler(path: str = ".") -> str:
    p = Path(path).resolve()
    if not p.is_dir():
        return f"Error: Not a directory: {path}"
    entries = []
    for item in sorted(p.iterdir()):
        kind = "DIR " if item.is_dir() else "FILE"
        size = item.stat().st_size if item.is_file() else 0
        entries.append(f"{kind} {item.name} ({size} bytes)")
    return "\n".join(entries) or "(empty directory)"


def build_tool_executor(provider: ZhipuProvider) -> ToolExecutor:
    executor = ToolExecutor(provider)

    executor.register(
        name="read_file",
        description="Read the contents of a file",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
        handler=_read_file_handler,
    )

    executor.register(
        name="write_file",
        description="Write content to a file",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file_handler,
    )

    executor.register(
        name="run_command",
        description="Execute a shell command",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
            },
            "required": ["command"],
        },
        handler=_run_command_handler,
    )

    executor.register(
        name="list_files",
        description="List files in a directory",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: project root)",
                    "default": ".",
                },
            },
        },
        handler=_list_files_handler,
    )

    executor.register(
        name="search_codebase",
        description="Search the codebase using semantic similarity. Returns relevant code snippets.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query describing what code to find",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_search_codebase_handler,
    )

    return executor


async def _search_codebase_handler(query: str, n_results: int = 5) -> str:
    results = search_code(query, n_results=n_results)
    if not results:
        return "No results found. The project may need to be indexed first."
    output_lines = ["Found relevant code snippets:\n"]
    for r in results:
        meta = r.get("metadata", {})
        output_lines.append(f"--- {meta.get('file_path', 'unknown')} (L{meta.get('start_line', '?')}-{meta.get('end_line', '?')}) [{meta.get('chunk_type', '')}: {meta.get('name', '')}] ---")
        output_lines.append(r.get("content", ""))
        output_lines.append("")
    return "\n".join(output_lines)
