"""Web tools: web_search, web_fetch."""
from __future__ import annotations

import asyncio

from app.llm.tools._common import get_http_client, import_ddgs, strip_html

TOOLS = []


async def web_search(query: str, max_results: int = 5) -> str:
    ddgs = import_ddgs()
    if ddgs is None:
        return "Error: duckduckgo-search not installed. Run: pip install duckduckgo-search"
    try:
        # ddgs.text() is a synchronous blocking network call — run it off the
        # event loop so it can't freeze the CLI/server while waiting on the
        # network (and any concurrent streams/tools).
        results = await asyncio.to_thread(ddgs.text, query, max_results=max_results)
    except Exception as e:
        return f"Error searching: {e}"
    if not results:
        return "No search results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', 'No title')}")
        lines.append(f"   {r.get('href', '')}")
        lines.append(f"   {r.get('body', '')}")
        lines.append("")
    return "\n".join(lines)


TOOLS.append({
    "name": "web_search",
    "description": "Search the web. Returns titles, URLs, and snippets.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
        },
        "required": ["query"],
    },
    "handler": web_search,
    "risk_level": "medium",
    "allowed_agents": ["explore", "general", "plan", "review"],
    "audit": True,
    "rate_limit": 10,
})


async def web_fetch(url: str, max_length: int = 5000) -> str:
    client = get_http_client()
    try:
        resp = await client.get(url)
        if resp.status >= 400:
            return f"Error: HTTP {resp.status} fetching {url}"
    except Exception as e:
        return f"Error fetching URL: {e}"
    content_type = resp.headers.get("content-type", "")
    raw = await resp.read()
    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type:
        text = strip_html(text)
    if len(text) > max_length:
        text = text[:max_length] + f"\n... (truncated, {len(text)} total chars)"
    return text


TOOLS.append({
    "name": "web_fetch",
    "description": "Fetch URL and return text content. Strips HTML.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_length": {"type": "integer", "description": "Max chars to return (default 5000)", "default": 5000},
        },
        "required": ["url"],
    },
    "handler": web_fetch,
    "risk_level": "medium",
    "allowed_agents": ["explore", "general", "plan", "review"],
    "audit": True,
    "rate_limit": 15,
})
