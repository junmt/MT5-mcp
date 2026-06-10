"""FastMCP エントリポイント。全ツールを登録して stdio で起動する。仕様書 §3。"""

from __future__ import annotations

import atexit
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .config import CONFIG
from .connection import shutdown
from .tools import account, analysis, fibonacci, history, indicators, market, trade

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mt5_mcp.server")

mcp = FastMCP("mt5-mcp")

# 閲覧・分析系（常時登録）
market.register(mcp)
history.register(mcp)
account.register(mcp)
indicators.register(mcp)
fibonacci.register(mcp)
analysis.register(mcp)

# 発注系はマスタースイッチが有効な場合のみ登録（仕様書 §6-1）
if CONFIG.trade_enabled:
    trade.register(mcp)
    log.info("発注ツールを登録しました (MT5_TRADE_ENABLED=true)。")
else:
    log.info("発注ツールは無効です (MT5_TRADE_ENABLED=false)。閲覧/分析のみ提供します。")

atexit.register(shutdown)


def main() -> None:
    """MCP サーバーを起動。

    既定は stdio。`--http` 引数または MT5_MCP_TRANSPORT=http で HTTP(streamable-http) 起動。
    """
    use_http = ("--http" in sys.argv) or (os.getenv("MT5_MCP_TRANSPORT", "").lower() == "http")
    if use_http:
        from .http_server import serve_http

        serve_http(mcp)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
