"""MCP server: search markdown runbooks."""

import json
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.config import get_settings

mcp = FastMCP("runbooks")


def _words(text: str) -> set[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # split CamelCase alert names
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def best_matches(directory: Path, base_url: str, query: str, top: int = 2) -> list[dict]:
    q = _words(query)
    scored = []
    for p in sorted(directory.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text else p.stem
        # title/filename words count triple, body words once
        head = _words(title + " " + p.stem.replace("-", " "))
        score = 3 * len(q & head) + len(q & _words(text))
        if score:
            scored.append(
                {"name": p.stem, "title": title, "url": f"{base_url}/{p.name}", "score": score}
            )
    return sorted(scored, key=lambda m: -m["score"])[:top]


@mcp.tool()
def search_runbooks(query: str) -> str:
    """Find the best-matching runbooks for an alert name or symptom. Returns name, title, URL."""
    s = get_settings()
    return json.dumps(best_matches(Path(s.runbooks_dir), s.runbook_base_url, query))


@mcp.tool()
def get_runbook(name: str) -> str:
    """Return the full markdown of a runbook by name (as returned by search_runbooks)."""
    p = Path(get_settings().runbooks_dir) / f"{Path(name).stem}.md"
    return p.read_text(encoding="utf-8") if p.exists() else f"ERROR: no runbook named {name}"


if __name__ == "__main__":
    mcp.run()
