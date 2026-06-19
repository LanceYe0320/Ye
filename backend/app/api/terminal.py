from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_verified_project, project_root
from app.rate_limit import limiter
from app.sandbox.runner import CommandResult, run_command
from app.storage.models import Project

router = APIRouter(prefix="/api/projects/{project_id}/terminal", tags=["terminal"])


class CommandRequest(BaseModel):
    command: str
    timeout: Optional[int] = None


class CommandResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


@router.post("/execute", response_model=CommandResponse)
@limiter.limit("30/minute")
async def execute_command(
    request: Request,
    project_id: int,
    data: CommandRequest,
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    result: CommandResult = await run_command(
        command=data.command,
        cwd=root,
        timeout=data.timeout,
    )
    return CommandResponse(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
    )
