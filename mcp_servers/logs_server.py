"""MCP server: search the demo service's JSON log file."""

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.config import get_settings

mcp = FastMCP("logs")
TAIL_BYTES = 4_000_000  # shortcut: only the file tail is scanned; use a log store if this grows


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - TAIL_BYTES))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def search(
    path: Path, minutes: int = 15, level: str = "", keyword: str = "", limit: int = 10
) -> dict:
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    kw, lvl = keyword.lower(), level.upper()
    hits = []
    for r in _read_records(path):
        try:
            ts = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        if ts < cutoff or (lvl and r.get("level") != lvl):
            continue
        if kw and kw not in json.dumps(r).lower():
            continue
        hits.append(r)
    groups = Counter(re.sub(r"\d+", "#", r.get("msg", "")) for r in hits)
    return {
        "matched": len(hits),
        "top_messages": [{"msg": m, "count": c} for m, c in groups.most_common(5)],
        "latest": hits[-limit:],
    }


@mcp.tool()
def search_logs(minutes: int = 15, level: str = "", keyword: str = "", limit: int = 10) -> str:
    """Search structured JSON logs. Filters: time window in minutes, level (ERROR/WARN/INFO),
    keyword substring. Returns match count, most frequent messages and the latest raw lines."""
    result = search(Path(get_settings().log_file), minutes, level, keyword, min(limit, 50))
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
