import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from app.config import settings
from app.llm.base_provider import ChatMessage, ToolCall
from app.llm.tool_executor import ToolExecutor
from app.llm.tools import build_tool_executor
from app.llm.zhipu_provider import ZhipuProvider

console = Console()

BANNER = """[bold cyan]Ye AI Coding Assistant[/] v{version}
[dim]Powered by {model} | Type /help for commands, Ctrl+C to exit[/]"""

HELP_TEXT = """[bold]Available Commands:[/]

  [cyan]/help[/]        Show this help
  [cyan]/model[/]       Show or switch model ([dim]/model glm-4-flash[/])
  [cyan]/clear[/]       Clear conversation history
  [cyan]/cd <path>[/]   Change working directory
  [cyan]/pwd[/]         Show current working directory
  [cyan]/edit <file>[/] Open file for editing
  [cyan]/exit[/]        Exit the assistant
"""


def main():
    asyncio.run(_run())


async def _run():
    console.print(BANNER.format(version=settings.VERSION, model=settings.ZHIPU_MODEL))
    console.print()

    if not settings.ZHIPU_API_KEY:
        console.print("[bold red]Error: ZHIPU_API_KEY not set.[/]")
        console.print("Set it via environment variable or .env file:")
        console.print("  [dim]export ZHIPU_API_KEY=your-key-here[/]")
        sys.exit(1)

    provider = ZhipuProvider()
    executor = build_tool_executor(provider)

    messages: list[ChatMessage] = [_system_prompt()]
    model = settings.ZHIPU_MODEL
    cwd = Path.cwd()

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory

        history_file = Path.home() / ".ye_history"
        session: PromptSession = PromptSession(history=FileHistory(str(history_file)))
    except Exception:
        session = None

    while True:
        try:
            if session:
                user_input = await asyncio.to_thread(
                    session.prompt, f"\001\033[1;36m\002ye>\001\033[0m\002 "
                )
            else:
                user_input = input("\033[1;36mye>\033[0m ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye![/]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            handled, messages, model, cwd = await _handle_command(
                user_input, messages, model, cwd
            )
            if handled == "exit":
                break
            continue

        messages.append(ChatMessage(role="user", content=user_input))

        console.print()
        assistant_content = ""
        tool_calls_data = []

        try:
            async for chunk in executor.run_agentic_loop(messages=messages, model=model):
                if chunk.type == "text_delta":
                    console.print(chunk.text, end="", highlight=False)
                    assistant_content += chunk.text

                elif chunk.type == "tool_call_end":
                    tool_calls_data.append({
                        "id": chunk.tool_call_id,
                        "name": chunk.tool_call_name,
                        "arguments": chunk.tool_call_arguments,
                    })

                elif chunk.type == "tool_execution_start":
                    console.print()
                    console.print(
                        f"  [dim bold]\\_ Running: [cyan]{chunk.text}[/][/]  ",
                        end="",
                    )

                elif chunk.type == "tool_execution_result":
                    result_text = chunk.text[:300]
                    if len(chunk.text) > 300:
                        result_text += "..."
                    console.print(f"[dim green]done[/]")
                    console.print(Panel(result_text, border_style="dim", padding=(0, 1)))

                elif chunk.type == "error":
                    console.print(f"\n[bold red]Error:[/] {chunk.text}")
                    break

            console.print("\n")

            if assistant_content or tool_calls_data:
                messages.append(ChatMessage(
                    role="assistant",
                    content=assistant_content,
                    tool_calls=[
                        ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                        for tc in tool_calls_data
                    ] if tool_calls_data else [],
                ))

        except Exception as e:
            console.print(f"\n[bold red]Error:[/] {e}\n")


async def _handle_command(cmd: str, messages, model, cwd):
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/exit", "/quit", "/q"):
        console.print("[dim]Bye![/]")
        return "exit", messages, model, cwd

    if command == "/help":
        console.print(HELP_TEXT)

    elif command == "/model":
        if arg:
            model = arg.strip()
            console.print(f"[cyan]Model switched to:[/] {model}")
        else:
            console.print(f"[cyan]Current model:[/] {model}")
            console.print("[dim]Available: glm-4-plus, glm-4-flash, glm-4-long, glm-4[/]")

    elif command == "/clear":
        messages.clear()
        messages.append(_system_prompt())
        console.print("[dim]Conversation cleared.[/]")

    elif command == "/pwd":
        console.print(str(cwd))

    elif command == "/cd":
        if not arg:
            console.print("[dim]Usage: /cd <path>[/]")
        else:
            new_cwd = (cwd / arg).resolve()
            if new_cwd.is_dir():
                import os
                os.chdir(new_cwd)
                cwd = new_cwd
                console.print(f"[dim]Changed to:[/] {cwd}")
            else:
                console.print(f"[red]Not a directory:[/] {new_cwd}")

    elif command == "/edit":
        if not arg:
            console.print("[dim]Usage: /edit <file>[/]")
        else:
            await _edit_file(arg.strip(), cwd)

    else:
        console.print(f"[dim]Unknown command:[/] {command}. Type /help for available commands.")

    return "ok", messages, model, cwd


async def _edit_file(file_path: str, cwd: Path):
    p = (cwd / file_path).resolve()
    if not p.is_file():
        console.print(f"[red]File not found:[/] {p}")
        return

    content = p.read_text(encoding="utf-8")
    console.print(Panel(
        f"[bold]{p.name}[/] ({len(content.splitlines())} lines)\n\n"
        f"[dim]--- first 20 lines ---[/]",
        border_style="cyan",
    ))
    for i, line in enumerate(content.splitlines()[:20], 1):
        console.print(f"  [dim]{i:4d} |[/] {line}")
    console.print()

    try:
        from prompt_toolkit import PromptSession
        session = PromptSession()
        instruction = await asyncio.to_thread(
            session.prompt, "Edit instruction: "
        )
    except (EOFError, KeyboardInterrupt):
        return
    except Exception:
        instruction = input("Edit instruction: ")

    if not instruction.strip():
        return

    console.print("\n[dim]Applying edit...[/]")


def _system_prompt() -> ChatMessage:
    return ChatMessage(
        role="system",
        content=(
            "You are Ye, an AI coding assistant running in the user's terminal. "
            "You can read/write files, run commands, and help with coding tasks. "
            "Be concise and direct. Use tools when needed. "
            "Format code with markdown code blocks."
        ),
    )


if __name__ == "__main__":
    main()
