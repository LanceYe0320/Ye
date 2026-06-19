from __future__ import annotations
import logging

import asyncio
import sys



logger = logging.getLogger(__name__)
if sys.platform != "win32":
    import resource

MAX_MEMORY_MB = 512
MAX_OPEN_FILES = 256
MAX_CPU_SECONDS = 120


def apply_limits():
    """Apply resource limits to the current process. Call in child/fork if available."""
    if sys.platform == "win32":
        return

    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (MAX_MEMORY_MB * 1024 * 1024, MAX_MEMORY_MB * 1024 * 1024),
        )
    except (ValueError, resource.error):
        pass

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(soft, MAX_OPEN_FILES), hard))
    except (ValueError, resource.error):
        pass

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_SECONDS, MAX_CPU_SECONDS))
    except (ValueError, resource.error):
        pass


class ResourceMonitor:
    """Async monitor that kills a subprocess if it exceeds limits."""

    def __init__(self, proc: asyncio.subprocess.Process, max_memory_mb: int = MAX_MEMORY_MB):
        self.proc = proc
        self.max_memory_mb = max_memory_mb
        self._task: asyncio.Task | None = None

    def start(self):
        if sys.platform == "win32":
            return
        self._task = asyncio.create_task(self._monitor())

    def stop(self):
        if self._task:
            self._task.cancel()

    async def _monitor(self):
        try:
            while self.proc.returncode is None:
                await asyncio.sleep(1)
                try:
                    import psutil
                    p = psutil.Process(self.proc.pid)
                    mem_mb = p.memory_info().rss / (1024 * 1024)
                    if mem_mb > self.max_memory_mb:
                        self.proc.kill()
                        break
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
