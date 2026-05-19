from httpx import AsyncClient


async def test_create_project(client: AsyncClient, auth_headers: dict, tmp_path):
    resp = await client.post("/api/projects/", json={
        "name": "Test Project",
        "path": str(tmp_path),
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Project"
    assert data["path"] == str(tmp_path)


async def test_list_projects(client: AsyncClient, auth_headers: dict, tmp_path):
    (tmp_path / "p1").mkdir()
    await client.post("/api/projects/", json={
        "name": "Project 1",
        "path": str(tmp_path / "p1"),
    }, headers=auth_headers)
    resp = await client.get("/api/projects/", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_list_files(client: AsyncClient, project_id: int, auth_headers: dict):
    resp = await client.get(f"/api/projects/{project_id}/files/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_write_and_read_file(client: AsyncClient, project_id: int, auth_headers: dict):
    content = "Hello, World!"
    resp = await client.put(
        f"/api/projects/{project_id}/files/test.txt",
        json={"content": content},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.get(f"/api/projects/{project_id}/files/test.txt", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["content"] == content


async def test_path_traversal_blocked(client: AsyncClient, project_id: int, auth_headers: dict):
    resp = await client.get(
        f"/api/projects/{project_id}/files/..%2F..%2Fetc%2Fpasswd",
        headers=auth_headers,
    )
    assert resp.status_code in (403, 404)


async def test_delete_file(client: AsyncClient, project_id: int, auth_headers: dict):
    await client.put(
        f"/api/projects/{project_id}/files/delete_me.txt",
        json={"content": "to delete"},
        headers=auth_headers,
    )
    resp = await client.delete(
        f"/api/projects/{project_id}/files/delete_me.txt",
        headers=auth_headers,
    )
    assert resp.status_code == 200
