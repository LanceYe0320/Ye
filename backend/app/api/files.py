from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_verified_project, project_root
from app.sandbox.runner import run_command
from app.storage.models import Project

router = APIRouter(prefix="/api/projects/{project_id}/files", tags=["files"])


def safe_path(root: Path, rel_path: str) -> Path:
    """Ensure rel_path stays within root directory."""
    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(403, "Path traversal detected")
    return target


class FileContent(BaseModel):
    content: str


class FileWrite(BaseModel):
    content: str


class DirEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int = 0


class CreateEntry(BaseModel):
    name: str
    is_dir: bool = False


@router.get("/", response_model=list[DirEntry])
async def list_files(
    project_id: int,
    path: str = Query(""),
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    target = safe_path(root, path)
    if not target.is_dir():
        raise HTTPException(400, "Not a directory")

    entries = []
    for item in sorted(target.iterdir()):
        rel = str(item.relative_to(root)).replace("\\", "/")
        entries.append(
            DirEntry(
                name=item.name,
                path=rel,
                is_dir=item.is_dir(),
                size=item.stat().st_size if item.is_file() else 0,
            )
        )
    return entries


@router.post("/")
async def create_entry(
    project_id: int,
    data: CreateEntry,
    path: str = Query(""),
    project: Project = Depends(get_verified_project),
):
    name = data.name.strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid name")
    root = project_root(project)
    base = safe_path(root, path) if path else root
    if not base.is_dir():
        raise HTTPException(400, "Not a directory")
    target = base / name
    resolved = target.resolve()
    if not str(resolved).startswith(str(root)):
        raise HTTPException(403, "Path traversal detected")
    if target.exists():
        raise HTTPException(409, "Already exists")
    if data.is_dir:
        target.mkdir(parents=False, exist_ok=False)
    else:
        target.write_text("", encoding="utf-8")
    rel = str(target.relative_to(root)).replace("\\", "/")
    return {"ok": True, "path": rel, "is_dir": data.is_dir}


@router.get("/{file_path:path}")
async def read_file(
    project_id: int,
    file_path: str,
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    target = safe_path(root, file_path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = f"[Binary file, {target.stat().st_size} bytes]"
    return {"path": file_path, "content": content}


@router.put("/{file_path:path}")
async def write_file(
    project_id: int,
    file_path: str,
    data: FileWrite,
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    target = safe_path(root, file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data.content, encoding="utf-8")
    return {"ok": True, "path": file_path}


@router.delete("/{file_path:path}")
async def delete_file(
    project_id: int,
    file_path: str,
    project: Project = Depends(get_verified_project),
):
    root = project_root(project)
    target = safe_path(root, file_path)
    if not target.exists():
        raise HTTPException(404, "File not found")
    if target.is_dir():
        import shutil
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True}
