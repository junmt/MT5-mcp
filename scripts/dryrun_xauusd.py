"""取引可能銘柄 XAUUSD で MCP 発注ツールのドライランを確認（実発注なし）。"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from mt5_mcp import server

m = server.mcp
SYMBOL = "XAUUSD"


async def call(name, args):
    res = await m.call_tool(name, args)
    if isinstance(res, tuple):
        if isinstance(res[1], dict):
            return res[1]
        res = res[0]
    if isinstance(res, list) and res:
        text = getattr(res[0], "text", None)
        if text:
            return json.loads(text)
    return res


async def main():
    r = await call("mt5_order_send",
                   {"symbol": SYMBOL, "side": "buy", "volume": 0.01, "type": "market"})
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
