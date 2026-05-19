import asyncio
import os
from pathlib import Path

from app.config import settings
from app.sandbox.permissions import is_command_allowed


class CommandResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


async def run_command(
    command: str,
    cwd: str | Path | None = None,
    timeout: int | None = None,
    env: dict | None = None,
    custom_allowlist: list[str] | None = None,
) -> CommandResult:
    allowed, reason = is_command_allowed(command, custom_allowlist)
    if not allowed:
        return CommandResult(exit_code=-1, stdout="", stderr=f"Command denied: {reason}")

    timeout = timeout or settings.COMMAND_TIMEOUT
    cwd = str(cwd) if cwd else None

    run_env = dict(os.environ)
    run_env.pop("ZHIPU_API_KEY", None)
    run_env.pop("SECRET_KEY", None)
    if env:
        run_env.update(env)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=run_env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")[: settings.MAX_OUTPUT_SIZE]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[: settings.MAX_OUTPUT_SIZE]

        return CommandResult(exit_code=proc.returncode or 0, stdout=stdout, stderr=stderr)

    except Exception as e:
        return CommandResult(exit_code=-1, stdout="", stderr=str(e))


async def stream_command(
    command: str,
    cwd: str | Path | None = None,
    timeout: int | None = None,
    custom_allowlist: list[str] | None = None,
    process_holder: dict | None = None,
):
    allowed, reason = is_command_allowed(command, custom_allowlist)
    if not allowed:
        yield {"type": "error", "data": f"Command denied: {reason}"}
        return

    timeout = timeout or settings.COMMAND_TIMEOUT
    cwd = str(cwd) if cwd else None

    run_env = dict(os.environ)
    run_env.pop("ZHIPU_API_KEY", None)
    run_env.pop("SECRET_KEY", None)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=run_env,
        )

        if process_holder is not None:
            process_holder["proc"] = proc

        queue: asyncio.Queue = asyncio.Queue()

        async def _read(stream, name):
            while True:
                line = await stream.readline()
                if not line:
                    break
                await queue.put({"type": name, "data": line.decode("utf-8", errors="replace")})
            await queue.put(None)

        stdout_task = asyncio.create_task(_read(proc.stdout, "stdout"))
        stderr_task = asyncio.create_task(_read(proc.stderr, "stderr"))
        pending_readers = 2

        while pending_readers > 0:
            item = await asyncio.wait_for(queue.get(), timeout=timeout)
            if item is None:
                pending_readers -= 1
                continue
            yield item

        await asyncio.gather(stdout_task, stderr_task)
        await proc.wait()
        yield {"type": "exit", "data": str(proc.returncode)}

    except asyncio.TimeoutError:
        yield {"type": "error", "data": f"Command timed out after {timeout}s"}
    except Exception as e:
        yield {"type": "error", "data": str(e)}
