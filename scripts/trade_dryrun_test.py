"""発注ツールのドライラン確認（confirm を付けないので実発注しません）。

使い方: py scripts/trade_dryrun_test.py [SYMBOL]
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from mt5_mcp import server

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "USDJPY"
m = server.mcp


async def call(name, args):
    res = await m.call_tool(name, args)
    if isinstance(res, tuple):
        content, structured = res[0], res[1]
        if isinstance(structured, dict):
            return structured
        res = content
    if isinstance(res, list) and res:
        text = getattr(res[0], "text", None)
        if text:
            return json.loads(text)
    return res


async def main():
    tools = [t.name for t in await m.list_tools()]
    print("TRADE TOOLS REGISTERED:", [t for t in tools if any(k in t for k in ("order", "position", "close_all"))])
    print()

    # confirm を付けない → ドライラン（プレビュー）になるはず。実発注なし。
    r = await call("mt5_order_send", {"symbol": SYMBOL, "side": "buy", "volume": 0.01, "type": "market"})
    print("=== mt5_order_send (no confirm → dry_run) ===")
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    print()

    # ロット上限超過 → SAFETY_BLOCKED になるはず
    r2 = await call("mt5_order_send", {"symbol": SYMBOL, "side": "buy", "volume": 5.0, "type": "market"})
    print("=== mt5_order_send (volume 5.0 > MAX_LOT) ===")
    print(json.dumps(r2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
