import subprocess

from httpx import AsyncClient


def _init_git_repo(path):
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), check=True, capture_output=True)


async def test_git_status(client: AsyncClient, project_id: int, auth_headers: dict, tmp_path):
    _init_git_repo(tmp_path)
    resp = await client.get(f"/api/projects/{project_id}/git/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "branch" in data
    assert "staged" in data
    assert "unstaged" in data
    assert "untracked" in data


async def test_git_log(client: AsyncClient, project_id: int, auth_headers: dict, tmp_path):
    _init_git_repo(tmp_path)
    resp = await client.get(f"/api/projects/{project_id}/git/log?count=5", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_git_branches(client: AsyncClient, project_id: int, auth_headers: dict, tmp_path):
    _init_git_repo(tmp_path)
    resp = await client.get(f"/api/projects/{project_id}/git/branches", headers=auth_headers)
    assert resp.status_code == 200
    branches = resp.json()
    assert isinstance(branches, list)
    assert any(b["active"] for b in branches)


async def test_git_diff(client: AsyncClient, project_id: int, auth_headers: dict, tmp_path):
    _init_git_repo(tmp_path)
    resp = await client.get(f"/api/projects/{project_id}/git/diff", headers=auth_headers)
    assert resp.status_code == 200
    assert "diff" in resp.json()
