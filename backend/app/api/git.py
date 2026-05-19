import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_verified_project, project_root
from app.sandbox.runner import run_command
from app.storage.models import Project

router = APIRouter(prefix="/api/projects/{project_id}/git", tags=["git"])


class GitStatus(BaseModel):
    branch: str
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]


class GitCommit(BaseModel):
    message: str
    files: list[str] | None = None


class GitDiff(BaseModel):
    files: list[str] | None = None
    staged: bool = False


class GitCheckout(BaseModel):
    branch: str
    create: bool = False


async def _git(project_path: str, *args: str) -> str:
    for arg in args:
        if re.search(r'[;&|`$]', arg):
            raise HTTPException(400, f"Invalid git argument: {arg}")
    cmd = "git " + " ".join(args)
    result = await run_command(cmd, cwd=project_path)
    output = result.stdout
    if result.exit_code != 0:
        raise HTTPException(400, f"Git error: {result.stderr or output}")
    return output


@router.get("/status")
async def git_status(project_id: int, project: Project = Depends(get_verified_project)):
    root = project_root(project)
    output = await _git(str(root), "status", "--porcelain=v1", "--branch")
    lines = output.strip().splitlines()
    branch = "unknown"
    staged, unstaged, untracked = [], [], []

    for line in lines:
        if line.startswith("## "):
            branch = line[3:].split("...")[0]
            continue
        if len(line) < 4:
            continue
        x, y = line[0], line[1]
        path = line[3:]
        if x in ("M", "A", "D", "R"):
            staged.append(path)
        if y in ("M", "D"):
            unstaged.append(path)
        if line.startswith("?? "):
            untracked.append(path)

    return GitStatus(branch=branch, staged=staged, unstaged=unstaged, untracked=untracked)


@router.get("/log")
async def git_log(
    project_id: int,
    count: int = Query(20, ge=1, le=100),
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    output = await _git(str(root), "log", f"-{count}", "--pretty=format:%H%x7C%an%x7C%ar%x7C%s")
    commits = []
    for line in output.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
    return commits


@router.get("/diff")
async def git_diff(
    project_id: int,
    staged: bool = False,
    file: str | None = None,
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    args = ["diff"]
    if staged:
        args.append("--staged")
    if file:
        args.append("--")
        args.append(file)
    output = await _git(str(root), *args)
    return {"diff": output}


@router.post("/commit")
async def git_commit(
    project_id: int,
    data: GitCommit,
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)

    if data.files:
        for f in data.files:
            await _git(str(root), "add", f)
    else:
        await _git(str(root), "add", "-A")

    output = await _git(str(root), "commit", "-m", data.message)
    return {"ok": True, "output": output}


@router.post("/commit-ai")
async def git_commit_ai(
    project_id: int,
    project: Project = Depends(get_verified_project),
):
    """AI generates commit message from staged diff."""
    root = project_root(project)
    diff_output = await _git(str(root), "diff", "--staged")

    if not diff_output.strip():
        await _git(str(root), "add", "-A")
        diff_output = await _git(str(root), "diff", "--staged")

    if not diff_output.strip():
        return {"ok": False, "error": "No changes to commit"}

    from app.llm.zhipu_provider import ZhipuProvider
    from app.llm.base_provider import ChatMessage

    provider = ZhipuProvider()
    messages = [
        ChatMessage(role="system", content="You are a git commit message generator. Generate a concise, conventional commit message based on the diff. Use conventional commits format (feat/fix/refactor/docs/chore). Reply with ONLY the commit message, no explanation."),
        ChatMessage(role="user", content=f"Generate a commit message for this diff:\n\n{diff_output[:4000]}"),
    ]

    commit_msg = ""
    async for chunk in provider.chat(messages=messages, max_tokens=200, temperature=0.3):
        if chunk.type == "text_delta":
            commit_msg += chunk.text

    commit_msg = commit_msg.strip()
    if not commit_msg:
        commit_msg = "chore: update files"

    output = await _git(str(root), "commit", "-m", commit_msg)
    return {"ok": True, "message": commit_msg, "output": output}


@router.get("/branches")
async def git_branches(project_id: int, project: Project = Depends(get_verified_project)):
    root = project_root(project)
    output = await _git(str(root), "branch", "--list")
    branches = []
    for line in output.strip().splitlines():
        line = line.strip()
        if line:
            active = line.startswith("*")
            name = line.lstrip("* ").strip()
            branches.append({"name": name, "active": active})
    return branches


@router.post("/checkout")
async def git_checkout(
    project_id: int,
    data: GitCheckout,
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    args = ["checkout"]
    if data.create:
        args.append("-b")
    args.append(data.branch)
    output = await _git(str(root), *args)
    return {"ok": True, "output": output}


@router.post("/review")
async def git_review(
    project_id: int,
    project: Project = Depends(get_verified_project),
):
    """AI reviews the current diff and provides feedback."""
    root = project_root(project)
    diff_output = await _git(str(root), "diff", "--staged")

    if not diff_output.strip():
        diff_output = await _git(str(root), "diff")

    if not diff_output.strip():
        return {"review": "No changes to review."}

    from app.llm.zhipu_provider import ZhipuProvider
    from app.llm.base_provider import ChatMessage

    provider = ZhipuProvider()
    messages = [
        ChatMessage(role="system", content="You are a code reviewer. Analyze the diff and provide concise feedback. Focus on: bugs, security issues, performance, readability. Use bullet points."),
        ChatMessage(role="user", content=f"Review this diff:\n\n{diff_output[:6000]}"),
    ]

    review = ""
    async for chunk in provider.chat(messages=messages, max_tokens=1000, temperature=0.3):
        if chunk.type == "text_delta":
            review += chunk.text

    return {"review": review or "No feedback."}
