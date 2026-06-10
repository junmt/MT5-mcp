"""実発注の往復テスト: XAUUSD 0.01ロットを成行で建てて即決済する。

⚠️ 実資金が動きます。本番口座での実行を想定。
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from mt5_mcp import server
from mt5_mcp.config import CONFIG

m = server.mcp
SYMBOL = "XAUUSD"
VOL = 0.01


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


def show(title, r):
    print(f"\n===== {title} =====")
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


async def main():
    print(f"MAX_LOT={CONFIG.max_lot}  magic={CONFIG.magic}  symbol={SYMBOL} vol={VOL}")

    # 0) 事前: 口座残高
    acc0 = await call("mt5_account_info", {})
    bal0 = acc0["data"]["balance"]
    print(f"事前残高: {bal0}")

    # 1) 成行BUYを実発注 (confirm=true)
    open_res = await call("mt5_order_send", {
        "symbol": SYMBOL, "side": "buy", "volume": VOL, "type": "market",
        "comment": "mt5-mcp-roundtrip", "confirm": True,
    })
    show("1) OPEN (market buy, confirm=true)", open_res)
    if not open_res.get("ok"):
        print("\n発注失敗のため中断します。")
        return

    # 2) ポジション確認
    pos = await call("mt5_positions", {"symbol": SYMBOL})
    show("2) POSITIONS", pos)
    targets = [p for p in pos["data"]["positions"] if p.get("magic") == CONFIG.magic]
    if not targets:
        print("\n対象ポジションが見つかりません。手動で確認してください。")
        return
    ticket = targets[-1]["ticket"]
    print(f"\n決済対象 ticket = {ticket}")

    # 3) 即時決済 (confirm=true)
    close_res = await call("mt5_position_close", {"ticket": ticket, "confirm": True})
    show("3) CLOSE (confirm=true)", close_res)

    # 4) 事後確認
    pos2 = await call("mt5_positions", {"symbol": SYMBOL})
    remaining = [p for p in pos2["data"]["positions"] if p.get("ticket") == ticket]
    print(f"\n決済後、同ticketの残ポジション: {len(remaining)} 件 (0 なら決済成功)")
    acc1 = await call("mt5_account_info", {})
    bal1 = acc1["data"]["balance"]
    print(f"事後残高: {bal1}  (損益込み差分: {round(bal1 - bal0, 2)})")


if __name__ == "__main__":
    asyncio.run(main())
