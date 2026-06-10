"""読み取り系ツールのスモークテスト（実MT5接続が必要）。

使い方: py scripts/smoke_test.py [SYMBOL]
発注は行いません（閲覧/分析のみ）。
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
    # FastMCP のバージョン差を吸収して dict を取り出す
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
    cases = [
        ("mt5_health_check", {}),
        ("mt5_quote", {"symbol": SYMBOL}),
        ("mt5_ohlcv", {"symbol": SYMBOL, "timeframe": "H1", "count": 50}),
        ("mt5_indicator", {"symbol": SYMBOL, "timeframe": "H1", "name": "rsi"}),
        ("mt5_indicators_batch", {"symbol": SYMBOL, "timeframe": "H1",
                                   "indicators": [{"name": "macd"}, {"name": "atr"}, {"name": "bollinger"}]}),
        ("mt5_swing_points", {"symbol": SYMBOL, "timeframe": "H1", "count": 200}),
        ("mt5_fib_retracement", {"symbol": SYMBOL, "timeframe": "H1", "auto": True}),
        ("mt5_fib_expansion", {"symbol": SYMBOL, "timeframe": "H1", "auto": True}),
        ("mt5_market_snapshot", {"symbol": SYMBOL, "timeframe": "H1"}),
        ("mt5_analyze", {"symbol": SYMBOL}),
        ("mt5_confluence", {"symbol": SYMBOL, "timeframe": "H1"}),
    ]
    for name, args in cases:
        try:
            r = await call(name, args)
            text = json.dumps(r, ensure_ascii=False, default=str)
            status = "OK " if (isinstance(r, dict) and r.get("ok")) else "ERR"
            print(f"[{status}] {name}: {text[:400]}")
        except Exception as exc:
            print(f"[EXC] {name}: {exc}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
