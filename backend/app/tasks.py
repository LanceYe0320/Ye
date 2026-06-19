"""Production-grade task management for Ye CLI — Phase 1 Harness.

Article reference: "Harness 第一层 — 任务生命周期"

State machine:
    created → planned → running → reviewing → completed
                         ↓           ↓
                      failed      failed
                      cancelled
                      timeout

Each task tracks: dependencies, priority, owner agent, timing, and outcome.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    CREATED = "created"
    PLANNED = "planned"
    RUNNING = "running"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Terminal states — tasks in these states cannot transition further
_TERMINAL_STATES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT}

# Valid transitions: current_state → set of allowed next states
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.PLANNED, TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.PLANNED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.REVIEWING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED},
    TaskStatus.REVIEWING: {TaskStatus.COMPLETED, TaskStatus.RUNNING, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.TIMEOUT: set(),
}


@dataclass
class TaskEvent:
    """An event in the task's lifecycle."""
    timestamp: float
    from_status: str
    to_status: str
    message: str = ""


@dataclass
class Task:
    id: int
    subject: str
    description: str = ""
    status: TaskStatus = TaskStatus.CREATED
    priority: TaskPriority = TaskPriority.MEDIUM
    owner: str = ""  # Agent role or "user"
    parent_id: int | None = None
    depends_on: list[int] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 0  # 0 = no timeout
    result: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    _events: list[TaskEvent] = field(default_factory=list)

    def transition(self, new_status: TaskStatus, message: str = "") -> bool:
        """Try to transition to a new status. Returns True if successful."""
        if self.status in _TERMINAL_STATES:
            return False
        if new_status not in _TRANSITIONS.get(self.status, set()):
            return False

        old = self.status
        self.status = new_status
        self._events.append(TaskEvent(
            timestamp=time.time(),
            from_status=old.value,
            to_status=new_status.value,
            message=message,
        ))

        if new_status == TaskStatus.RUNNING and self.started_at is None:
            self.started_at = time.time()
        if new_status in _TERMINAL_STATES:
            self.finished_at = time.time()

        return True

    def check_timeout(self) -> bool:
        """Check if this task has exceeded its timeout. Returns True if timed out."""
        if self.timeout_seconds <= 0 or self.status != TaskStatus.RUNNING:
            return False
        if self.started_at and (time.time() - self.started_at) > self.timeout_seconds:
            self.transition(TaskStatus.TIMEOUT, f"Exceeded {self.timeout_seconds}s timeout")
            return True
        return False

    def elapsed_seconds(self) -> float:
        """How long this task has been running (or ran)."""
        if self.started_at is None:
            return 0
        end = self.finished_at or time.time()
        return end - self.started_at

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATES

    @property
    def is_active(self) -> bool:
        return self.status not in _TERMINAL_STATES


class TaskManager:
    def __init__(self):
        self._tasks: list[Task] = []
        self._next_id = 1

    def create(
        self,
        subject: str,
        description: str = "",
        priority: str = "medium",
        owner: str = "",
        parent_id: int | None = None,
        depends_on: list[int] | None = None,
        timeout_seconds: int = 0,
    ) -> Task:
        task = Task(
            id=self._next_id,
            subject=subject,
            description=description,
            priority=TaskPriority(priority),
            owner=owner,
            parent_id=parent_id,
            depends_on=depends_on or [],
            timeout_seconds=timeout_seconds,
        )
        self._tasks.append(task)
        self._next_id += 1
        return task

    def get(self, task_id: int) -> Task | None:
        for t in self._tasks:
            if t.id == task_id:
                return t
        return None

    def list_all(self) -> list[Task]:
        return list(self._tasks)

    def list_active(self) -> list[Task]:
        return [t for t in self._tasks if t.is_active]

    def list_by_status(self, status: TaskStatus) -> list[Task]:
        return [t for t in self._tasks if t.status == status]

    def list_dependents(self, task_id: int) -> list[Task]:
        """Find tasks that depend on the given task."""
        return [t for t in self._tasks if task_id in t.depends_on]

    def are_dependencies_met(self, task_id: int) -> bool:
        """Check if all dependencies for a task are completed."""
        task = self.get(task_id)
        if task is None:
            return False
        for dep_id in task.depends_on:
            dep = self.get(dep_id)
            if dep is None or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def update_status(self, task_id: int, status: TaskStatus, message: str = "") -> Task | None:
        task = self.get(task_id)
        if task and task.transition(status, message):
            return task
        return None

    def delete(self, task_id: int) -> bool:
        for i, t in enumerate(self._tasks):
            if t.id == task_id:
                self._tasks.pop(i)
                return True
        return False

    def check_timeouts(self) -> list[Task]:
        """Check all active tasks for timeout. Returns list of timed-out tasks."""
        timed_out = []
        for t in self._tasks:
            if t.check_timeout():
                timed_out.append(t)
        return timed_out

    def format_tasks(self, show_all: bool = False) -> str:
        if not self._tasks:
            return "No tasks."

        tasks = self._tasks if show_all else [t for t in self._tasks if t.is_active]
        if not tasks:
            return "All tasks completed."

        lines = []
        for t in tasks:
            status_icons = {
                "created": "[?]", "planned": "[P]", "running": "[~]",
                "reviewing": "[R]", "completed": "[x]", "failed": "[!]",
                "cancelled": "[-]", "timeout": "[T]",
            }
            icon = status_icons.get(t.status.value, "[ ]")
            priority_mark = {"low": "", "medium": "", "high": "*", "critical": "!!"}.get(t.priority.value, "")
            elapsed = f" ({t.elapsed_seconds():.0f}s)" if t.started_at else ""

            line = f"  {icon} #{t.id} {priority_mark}{t.subject}{elapsed}"
            if t.owner:
                line += f" [{t.owner}]"
            lines.append(line)
            if t.description:
                lines.append(f"       {t.description}")
            if t.depends_on:
                lines.append(f"       depends on: #{', #'.join(str(d) for d in t.depends_on)}")

        return "\n".join(lines)

    def format_task_detail(self, task_id: int) -> str:
        task = self.get(task_id)
        if not task:
            return f"Task #{task_id} not found."

        lines = [
            f"  Task #{task.id}: {task.subject}",
            f"  Status: {task.status.value}",
            f"  Priority: {task.priority.value}",
            f"  Owner: {task.owner or 'unassigned'}",
            f"  Retries: {task.retry_count}/{task.max_retries}",
        ]
        if task.description:
            lines.append(f"  Description: {task.description}")
        if task.started_at:
            lines.append(f"  Elapsed: {task.elapsed_seconds():.1f}s")
        if task.depends_on:
            lines.append(f"  Depends on: #{', #'.join(str(d) for d in task.depends_on)}")
        if task.result:
            lines.append(f"  Result: {task.result[:200]}")
        if task._events:
            lines.append("  History:")
            for evt in task._events[-5:]:
                lines.append(f"    {evt.from_status} → {evt.to_status}: {evt.message or '-'}")

        return "\n".join(lines)
