# Architecture Overview

## System Architecture

```
┌─────────────┐     ┌─────────────┐
│   Desktop    │     │   Mobile    │
│  (Electron   │     │  (Flutter)  │
│   + Vue 3)   │     │             │
└──────┬───────┘     └──────┬──────┘
       │ HTTP/WS            │ HTTP/WS
       └────────┬───────────┘
                │
        ┌───────▼────────┐
        │  FastAPI Backend │
        │  (Python 3.12+) │
        └───┬────┬────┬───┘
            │    │    │
    ┌───────▼┐ ┌─▼──┐ ┌▼────────┐
    │SQLite  │ │智谱 │ │ChromaDB │
    │Database│ │ AI  │ │Vector DB│
    └────────┘ └─────┘ └─────────┘
```

## Backend Structure

### API Layer (`app/api/`)
- `auth.py` — JWT login/register
- `projects.py` — Project CRUD
- `files.py` — File read/write/delete with path traversal protection
- `terminal.py` — Command execution via sandbox
- `conversations.py` — Chat history CRUD
- `settings.py` — User preferences
- `search.py` — Semantic code search
- `git.py` — Git operations with AI commit/review
- `plugins.py` — Plugin management

### LLM Layer (`app/llm/`)
- `zhipu_provider.py` — Zhipu AI (GLM-4) via OpenAI-compatible API
- `tool_executor.py` — Agentic loop: LLM → tool call → execute → feed back
- `tools.py` — Tool definitions: read_file, write_file, run_command, list_files, search_codebase

### Sandbox (`app/sandbox/`)
- `runner.py` — Async subprocess execution with streaming output
- `permissions.py` — Command allowlist/denylist
- `resource_limits.py` — Memory/CPU limits

### WebSocket (`app/ws/`)
- `gateway.py` — Chat streaming + terminal streaming
- `sync_handler.py` — CRDT-style document sync

### Indexer (`app/indexer/`)
- `code_parser.py` — Python AST + heuristic chunking
- `vector_store.py` — ChromaDB persistent storage

## Desktop Structure

### Layout
```
┌──────────────────────────────────────────┐
│ TitleBar                                 │
├────┬──────────────────────┬──────────────┤
│Side│ FileTree │ Editor    │ Chat Panel   │
│bar │          │ (Monaco)  │              │
│    │──────────────────────│              │
│    │ Terminal (xterm.js)  │              │
├────┴──────────────────────┴──────────────┤
│ StatusBar                                │
└──────────────────────────────────────────┘
```

### Key Components
- `MonacoEditor.vue` — VS Code editor engine
- `EditorTabs.vue` — Multi-file tabs
- `DiffViewer.vue` — AI-suggested changes preview
- `XTermTerminal.vue` — Real-time terminal
- `ChatPanel.vue` — AI chat with markdown + tool call display

### State Management (Pinia)
- `project.js` — Projects, open files, active file
- `conversation.js` — Chat history, streaming state
- `settings.js` — User preferences

## Mobile Structure

### Navigation
Bottom navigation with 3 tabs: Chat | Files | Settings

### Key Screens
- `chat_screen.dart` — Conversation list + messages + streaming
- `file_browser_screen.dart` — File tree + view + edit
- `terminal_view_screen.dart` — Command input + output
- `settings_screen.dart` — Model/temperature/server config

## Data Flow

### Chat Flow
1. User sends message via WebSocket
2. Backend loads conversation history from SQLite
3. Sends to Zhipu AI with system prompt + history
4. LLM may return tool_calls (read_file, run_command, etc.)
5. Backend executes tools, feeds results back to LLM
6. Streams text_delta chunks to frontend in real-time
7. Saves final response to SQLite

### File Sync Flow
1. Client subscribes to a document via WebSocket
2. Server sends full state on subscribe
3. Client sends incremental updates
4. Server broadcasts updates to all other subscribers
5. Conflict-free via server-authoritative merge
