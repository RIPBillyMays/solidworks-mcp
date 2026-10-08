"""Offline smoke test for the solidworks-mcp stdio server.

Launches the server executable, performs the MCP initialize handshake and
list_tools, then prints the tool count, the sorted tool names and the server
instructions (if any). It never calls a tool, so SOLIDWORKS is not touched.

Usage:
    .venv\\Scripts\\python.exe tools\\compat\\mcp_smoke_client.py [path\\to\\solidworks-mcp.exe]
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_EXE = Path(__file__).resolve().parents[2] / ".venv" / "Scripts" / "solidworks-mcp.exe"


async def main(exe: str) -> int:
    params = StdioServerParameters(command=exe, args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = init.serverInfo
            print(f"server: {info.name} {info.version}")
            print(f"protocol: {init.protocolVersion}")
            print("instructions:", init.instructions if init.instructions else "(none)")

            result = await session.list_tools()
            names = sorted(t.name for t in result.tools)
            print(f"tool count: {len(names)}")
            print("tools:", ", ".join(names))
    return 0


if __name__ == "__main__":
    exe_path = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_EXE)
    sys.exit(asyncio.run(main(exe_path)))
