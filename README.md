# Ye / yjl — 自建 Claude Code（AI 编码助手）

一个对标 Claude Code 的跨平台 AI 编码助手，终端打 `yjl` 即可用。基于智谱 GLM（默认 glm-5.2，100 万上下文），纯 Python 后端 + FastAPI Web 服务 + Flutter 移动端 + Electron 桌面端。

## 快速开始

```bash
cd backend
.\install.ps1            # Windows（创建 venv、装依赖、写 .env）
# 或手动：pip install -e .

# 终端使用（从任意目录）
yjl                      # 启动交互式 REPL
yjl -p "你的问题"        # 单次问答（非交互）
yjl -r                   # 恢复上次会话
yjl --model glm-5.2      # 指定模型
yjl --version
```

> `yjl` 始终运行最新源码（通过 `python -m app.cli.main`）。旧的 `ye` 命令是独立的打包产品。

## 核心能力

### 对标 Claude Code 的完整能力

| 能力 | 命令/工具 | 说明 |
|---|---|---|
| **TodoWrite 实时任务追踪** | `todo_write` 工具 + `/todos` | 动态 todo 列表驱动长任务，注入系统提示保持方向 |
| **Skills 可复用过程** | `/<skill-name>` + `/skills` | SKILL.md 封装工作流，slash 触发或上下文自动触发 |
| **MCP 外部工具协议** | `/mcp` + 配置 | 连接 stdio/SSE 的 MCP 服务器，扩展工具生态 |
| **Plan 模式** | Shift+Tab 切换 | 只读分析，不修改文件 |
| **子 Agent 编排** | `spawn_agent` / `spawn_agent_group` | 并发子 agent，per-task CWD 隔离 |
| **三层记忆系统** | `/memory` `/remember` `/forget` `/prune` | core + persistent + 跨会话 FTS5 检索 |
| **会话持久化** | `/sessions` `/resume` | 保存/恢复会话 |
| **上下文压缩** | `/compact` + 自动触发 | 流式摘要，budget 熔断 |
| **成本/预算追踪** | `/cost` `/budget` | token 用量、估算费用、预算区控制 |
| **Git worktree** | `/worktree` | 并行工作分支 |
| **安全沙箱** | `/permissions` | 命令注入防护 + 工具权限 auto/ask/deny |
| **向量语义检索** | `search_codebase` | 增量索引（mtime 缓存），多语言解析 |

### 内置工具（17 个）

`read_file` `write_file` `edit_file` `append_file` `grep` `glob` `list_files` `project_overview` `search_codebase` `run_command` `web_search` `web_fetch` `ask_user` `spawn_agent` `spawn_agent_group` `todo_write`

---

## TodoWrite（实时任务追踪）

Claude Code 风格的动态 todo 列表，让 agent 在多步任务中保持方向。

- LLM 通过 `todo_write` 工具**整体替换**当前 todo 列表（每项：content / status / priority / active_form）
- todo 列表**每轮注入系统提示**（in_progress 排最前），驱动 agent 行为
- 每轮末尾显示进度 `todos: 1/3 done`
- `/todos` 查看完整列表（`[x]` 完成 / `[~]` 进行中 / `[ ]` 待办）

```
> /todos
┌─ TodoWrite ──────────────────────┐
│ Todos (1/3 done, updated 21:59)  │
│   [x] Read file                  │
│   [~] Edit code                  │
│   [ ] Run tests                  │
└──────────────────────────────────┘
```

## Skills 系统（可复用过程）

把常用工作流封装成 skill，`/<name>` 一键触发。

**创建 skill**：在 `.ye/skills/<name>/SKILL.md`（项目级）或 `~/.ye/skills/<name>/SKILL.md`（用户级）：

```markdown
---
name: refactor
description: Safely refactor a function with tests
triggers: refactor, restructure, cleanup code
---
When asked to refactor:
1. Read the target function fully.
2. Create a TodoWrite plan.
3. Make the smallest change preserving behavior.
4. Verify by reading the result.
```

**使用**：
```
> /skills          # 列出所有 skill
> /refactor        # 触发 refactor skill（注入指令进入 agentic loop）
```

项目级 skill 覆盖用户级同名 skill。

## MCP（外部工具协议）

连接任何 MCP 服务器，自动发现并调用其工具（与 Claude Code 生态兼容）。

**配置** `~/.ye/mcp_servers.json`：
```json
{
  "servers": {
    "sqlite": {
      "command": ["uvx", "mcp-server-sqlite", "--db-path", "data/app.db"]
    },
    "remote": {
      "url": "http://localhost:8080",
      "transport": "sse"
    }
  }
}
```

启动后自动连接（后台），工具以 `server__tool` 命名注册。`/mcp` 查看状态。服务器失败不影响其他功能。

---

## 配置

`.env` 文件（在 `backend/` 目录）：
```
ZHIPU_API_KEY=你的key
ZHIPU_MODEL=glm-5.2
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
SECRET_KEY=随机64位字符串
```

## 架构

```
backend/
  app/
    cli/          终端 REPL（yjl 入口）
    llm/          LLM provider + 工具执行器 + agentic loop
      tools/      17 个内置工具（插件式）
    ws/           WebSocket 网关
    api/          REST API
    indexer/      代码索引（多语言解析 + 向量检索）
    sandbox/      命令沙箱（注入防护）
    storage/      数据库（SQLite WAL）
    todo_store.py TodoWrite
    skills.py     Skills 系统
    mcp_client.py MCP 客户端
    memory.py     三层记忆
    sessions.py   会话持久化
mobile/           Flutter 移动端
desktop/          Electron 桌面端
```

## 开发

```bash
cd backend
pytest tests/ -q          # 测试（234 passed）
ruff check app/           # lint
```

## License

MIT
