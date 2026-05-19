# API Reference

Base URL: `http://localhost:8765`

## Authentication

### POST /api/auth/register
Register a new user.
```json
// Request
{ "username": "user", "password": "password123" }
// Response
{ "access_token": "jwt...", "token_type": "bearer", "user_id": 1, "username": "user" }
```

### POST /api/auth/login
Login and get JWT token.
```json
// Request
{ "username": "user", "password": "password123" }
// Response
{ "access_token": "jwt...", "token_type": "bearer", "user_id": 1, "username": "user" }
```

## Projects

### GET /api/projects/
List all projects.

### POST /api/projects/
Create a project.
```json
{ "name": "My Project", "path": "/path/to/project" }
```

### GET /api/projects/{id}
Get project details.

### DELETE /api/projects/{id}
Delete a project.

## Files

### GET /api/projects/{id}/files/?path=
List directory contents. `path` defaults to project root.

### GET /api/projects/{id}/files/{file_path}
Read file content.

### PUT /api/projects/{id}/files/{file_path}
Write file content.
```json
{ "content": "file content here" }
```

### DELETE /api/projects/{id}/files/{file_path}
Delete a file or directory.

## Terminal

### POST /api/projects/{id}/terminal/execute
Execute a command.
```json
{ "command": "ls -la", "timeout": 30 }
// Response
{ "exit_code": 0, "stdout": "...", "stderr": "" }
```

## Conversations

### GET /api/conversations/
List conversations.

### POST /api/conversations/
Create a conversation.
```json
{ "title": "New Chat", "project_id": 1, "model": "glm-4-plus" }
```

### GET /api/conversations/{id}/messages/
Get all messages in a conversation.

### DELETE /api/conversations/{id}
Delete a conversation.

## Search

### POST /api/projects/{id}/index
Index project code for semantic search.
```json
// Response
{ "indexed_chunks": 150, "status": "completed" }
```

### POST /api/projects/{id}/search
Semantic search across indexed code.
```json
{ "query": "authentication logic", "n_results": 10 }
```

## Git

### GET /api/projects/{id}/git/status
Get git status.

### GET /api/projects/{id}/git/log?count=20
Get commit log.

### GET /api/projects/{id}/git/diff?staged=false&file=path
Get diff.

### POST /api/projects/{id}/git/commit
Commit changes.
```json
{ "message": "feat: add login", "files": ["src/auth.py"] }
```

### POST /api/projects/{id}/git/commit-ai
AI-generates commit message from staged changes.

### GET /api/projects/{id}/git/branches
List branches.

### POST /api/projects/{id}/git/checkout
Checkout or create branch.
```json
{ "branch": "feature-x", "create": true }
```

### POST /api/projects/{id}/git/review
AI code review of current diff.

## Plugins

### GET /api/plugins/
List installed and active plugins.

### POST /api/plugins/{name}/activate?project_id=1
Activate a plugin.

### POST /api/plugins/{name}/deactivate
Deactivate a plugin.

## Settings

### GET /api/settings/
Get user settings.

### PUT /api/settings/
Update user settings.
```json
{ "settings": { "model": "glm-4-plus", "temperature": 0.7 } }
```

## WebSocket Endpoints

### WS /ws/chat/{conversation_id}
Chat streaming. Send: `{ "content": "...", "model": "glm-4-plus" }`
Receive: streaming chunks with types `text_delta`, `tool_call_start`, `tool_call_end`, `done`, `error`.

### WS /ws/terminal/{project_id}
Terminal streaming. Send: `{ "command": "ls" }`
Receive: `{ "type": "stdout|stderr|exit|error", "data": "..." }`

### WS /ws/sync
Document sync. Send: `{ "type": "subscribe|sync_update|unsubscribe", "doc_id": "..." }`
Receive: `{ "type": "sync_full|sync_update", ... }`
