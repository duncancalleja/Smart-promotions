"""
Refresh the Salesforce access token in .cursor/mcp.json.

Uses the Salesforce CLI's stored refresh token (from `sf org login web`)
to get a fresh access token and patch .cursor/mcp.json in place.

Usage:
    python3 refresh_sf_token.py            # auto-detect workspace root
    python3 refresh_sf_token.py /path/to   # explicit workspace root
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SF_USERNAME = "duncan.calleja@bolt.eu"
SF_INSTANCE_URL = "https://boltfood.my.salesforce.com"


def _find_workspace_root(start: Path | None = None) -> Path:
    """Walk up from start (or this script's dir) until we find .cursor/mcp.json."""
    p = start or Path(__file__).resolve().parent
    for ancestor in [p, *p.parents]:
        if (ancestor / ".cursor" / "mcp.json").exists():
            return ancestor
    raise FileNotFoundError("Could not locate .cursor/mcp.json above " + str(p))


def get_fresh_token() -> str:
    """Call the Salesforce CLI to get a current access token."""
    result = subprocess.run(
        ["npx", "-y", "@salesforce/cli", "org", "display",
         "--target-org", SF_USERNAME, "--json"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"sf org display failed (exit {result.returncode}):\n{result.stderr}"
        )
    data = json.loads(result.stdout)
    token = data["result"]["accessToken"]
    if not token:
        raise RuntimeError("accessToken was empty in sf org display output")
    return token


def patch_mcp_json(workspace: Path, token: str) -> Path:
    """Update SALESFORCE_ACCESS_TOKEN in .cursor/mcp.json and return the path."""
    mcp_path = workspace / ".cursor" / "mcp.json"
    cfg = json.loads(mcp_path.read_text())

    sf = cfg.setdefault("mcpServers", {}).setdefault("salesforce", {})
    env = sf.setdefault("env", {})
    old = env.get("SALESFORCE_ACCESS_TOKEN", "")
    env["SALESFORCE_ACCESS_TOKEN"] = token
    env.setdefault("SALESFORCE_INSTANCE_URL", SF_INSTANCE_URL)

    sf.setdefault("command", "salesforce")
    sf.setdefault("args", [])

    mcp_path.write_text(json.dumps(cfg, indent=2) + "\n")

    changed = old != token
    return mcp_path, changed


def main():
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    root = _find_workspace_root(workspace)

    print(f"Workspace: {root}")
    print(f"Fetching fresh token for {SF_USERNAME} ...")
    token = get_fresh_token()
    print(f"Token:     {token[:20]}...{token[-6:]}")

    mcp_path, changed = patch_mcp_json(root, token)
    if changed:
        print(f"Updated:   {mcp_path}")
        print("Restart Cursor (or reload window) to pick up the new token.")
    else:
        print(f"Token unchanged — {mcp_path} already current.")


if __name__ == "__main__":
    main()
