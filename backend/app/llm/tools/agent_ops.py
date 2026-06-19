"""Agent tools: spawn_agent, spawn_agent_group. Requires provider at registration time."""
from __future__ import annotations

import json

TOOLS = []


def make_agent_tools(provider):
    """Create agent tools bound to a provider instance. Returns list of tool defs."""
    async def spawn_agent_handler(task_description: str, agent_type: str = "general") -> str:
        from app.agents import spawn_agent
        import os
        return await spawn_agent(task_description, provider, agent_type=agent_type, cwd=os.getcwd())

    async def spawn_agent_group_handler(tasks) -> str:
        from app.agents import spawn_agent_group, format_group_results
        import os
        task_list = tasks if isinstance(tasks, list) else json.loads(tasks)
        results = await spawn_agent_group(tasks=task_list, provider=provider, cwd=os.getcwd())
        return format_group_results(results)

    return [
        {
            "name": "spawn_agent",
            "description": "Spawn a sub-agent for complex multi-step tasks. Do NOT use for simple reads/searches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {"type": "string", "description": "Task for the sub-agent"},
                    "agent_type": {
                        "type": "string",
                        "description": "Agent role: explore, general, plan, review, code",
                        "default": "general",
                        "enum": ["explore", "general", "plan", "review", "code"],
                    },
                },
                "required": ["task_description"],
            },
            "handler": spawn_agent_handler,
            "risk_level": "high",
            "allowed_agents": ["general"],
            "requires_approval": True,
            "audit": True,
            "timeout": 300,
        },
        {
            "name": "spawn_agent_group",
            "description": "Spawn MULTIPLE agents in PARALLEL. Each agent works independently.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "List of subtasks. Each: {\"task\": \"description\", \"type\": \"role\"}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "task": {"type": "string", "description": "Task description"},
                                "type": {
                                    "type": "string",
                                    "description": "Agent role (default: general)",
                                    "default": "general",
                                    "enum": ["explore", "general", "plan", "review", "code"],
                                },
                            },
                            "required": ["task"],
                        },
                    },
                },
                "required": ["tasks"],
            },
            "handler": spawn_agent_group_handler,
            "risk_level": "high",
            "allowed_agents": ["general"],
            "requires_approval": True,
            "audit": True,
            "timeout": 180,
        },
    ]
