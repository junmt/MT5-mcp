"""全機能テスト。閲覧/分析/指標/フィボ/発注(ドライラン)/安全ガード/エラー処理を網羅。

実発注(confirm=true)は行いません。本番口座でも安全に実行できます。
使い方: py scripts/full_test.py [SYMBOL]
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

PASS = 0
FAIL = 0
results = []


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


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        results.append(f"[PASS] {label}")
    else:
        FAIL += 1
        results.append(f"[FAIL] {label}  -> {detail}")


async def expect_ok(label, name, args, validate=None):
    r = await call(name, args)
    ok = isinstance(r, dict) and r.get("ok") is True
    if ok and validate:
        try:
            ok = validate(r["data"])
        except Exception as exc:  # noqa: BLE001
            ok = False
            r = {"validate_error": str(exc), **(r if isinstance(r, dict) else {})}
    check(label, ok, json.dumps(r, ensure_ascii=False, default=str)[:200])
    return r


async def expect_err(label, name, args, code=None):
    r = await call(name, args)
    is_err = isinstance(r, dict) and r.get("ok") is False
    if is_err and code:
        is_err = r["error"].get("code") == code
    check(label, is_err, json.dumps(r, ensure_ascii=False, default=str)[:200])
    return r


async def main():
    print(f"=== 全機能テスト SYMBOL={SYMBOL} ===\n")
    tool_names = [t.name for t in await m.list_tools()]
    check(f"ツール登録数 == 27 (実際 {len(tool_names)})", len(tool_names) == 27)

    # --- 接続/口座 ---
    await expect_ok("health_check connected", "mt5_health_check", {},
                    lambda d: d["connected"] is True)
    await expect_ok("account_info balance", "mt5_account_info", {},
                    lambda d: "balance" in d)
    await expect_ok("terminal_info", "mt5_terminal_info", {}, lambda d: "connected" in d)

    # --- マーケット ---
    await expect_ok("symbols_list", "mt5_symbols_list", {"limit": 10},
                    lambda d: d["count"] > 0 and len(d["symbols"]) <= 10)
    await expect_ok("symbols_list group filter", "mt5_symbols_list", {"group": "*USD*", "limit": 5},
                    lambda d: d["count"] >= 0)
    await expect_ok("symbol_info summary", "mt5_symbol_info", {"symbol": SYMBOL},
                    lambda d: d["summary"]["symbol"] == SYMBOL and d["summary"]["digits"] >= 0)
    await expect_ok("quote bid/ask", "mt5_quote", {"symbol": SYMBOL},
                    lambda d: d["bid"] > 0 and d["ask"] >= d["bid"])
    # market_depth: DOM非対応なら error でも許容（どちらかになることを確認）
    rd = await call("mt5_market_depth", {"symbol": SYMBOL})
    check("market_depth 応答(ok or err)", isinstance(rd, dict) and "ok" in rd)

    # --- ヒストリカル ---
    await expect_ok("ohlcv summary", "mt5_ohlcv", {"symbol": SYMBOL, "timeframe": "H1", "count": 50},
                    lambda d: d["summary"]["bars_count"] == 50 and "bars" not in d)
    await expect_ok("ohlcv full", "mt5_ohlcv", {"symbol": SYMBOL, "timeframe": "M15", "count": 30, "full": True},
                    lambda d: len(d["bars"]) == 30)
    await expect_ok("ohlcv count cap 5000", "mt5_ohlcv", {"symbol": SYMBOL, "timeframe": "M5", "count": 99999},
                    lambda d: d["summary"]["bars_count"] <= 5000)
    # ticks: 直近のバー時刻から
    q = await call("mt5_quote", {"symbol": SYMBOL})
    from_dt = q["data"]["time_utc"][:10] + "T00:00:00Z"
    await expect_ok("ticks", "mt5_ticks", {"symbol": SYMBOL, "from_date": from_dt, "count": 20},
                    lambda d: d["count"] >= 1)

    # --- 照会 ---
    await expect_ok("positions", "mt5_positions", {}, lambda d: "count" in d)
    await expect_ok("orders", "mt5_orders", {}, lambda d: "count" in d)
    await expect_ok("history_deals", "mt5_history_deals",
                    {"from_date": "2026-01-01T00:00:00Z", "to_date": from_dt}, lambda d: "count" in d)
    await expect_ok("history_orders", "mt5_history_orders",
                    {"from_date": "2026-01-01T00:00:00Z", "to_date": from_dt}, lambda d: "count" in d)

    # --- 指標 (全8種) ---
    for nm, params, key in [
        ("sma", {"period": 20}, "value"), ("ema", {"period": 20}, "value"),
        ("rsi", {"period": 14}, "value"), ("macd", {}, "macd"),
        ("bollinger", {}, "middle"), ("atr", {"period": 14}, "value"),
        ("stochastic", {}, "k"), ("adx", {}, "adx"),
    ]:
        await expect_ok(f"indicator {nm}", "mt5_indicator",
                        {"symbol": SYMBOL, "timeframe": "H1", "name": nm, "params": params},
                        lambda d, k=key: d["result"].get(k) is not None)
    await expect_ok("indicators_batch", "mt5_indicators_batch",
                    {"symbol": SYMBOL, "timeframe": "H1", "indicators": [{"name": "rsi"}, {"name": "macd"}]},
                    lambda d: len(d["indicators"]) == 2)

    # --- フィボナッチ ---
    await expect_ok("swing_points", "mt5_swing_points", {"symbol": SYMBOL, "timeframe": "H1", "count": 200},
                    lambda d: d["count"] >= 1)
    await expect_ok("fib_retracement auto", "mt5_fib_retracement",
                    {"symbol": SYMBOL, "timeframe": "H1", "auto": True},
                    lambda d: len(d["levels"]) == 7 and d["auto_swings"] is not None)
    await expect_ok("fib_retracement manual up", "mt5_fib_retracement",
                    {"symbol": SYMBOL, "timeframe": "H1", "high": 161.0, "low": 160.0, "direction": "up"},
                    lambda d: any(abs(l["price"] - 160.5) < 1e-6 for l in d["levels"] if l["level"] == 0.5))
    await expect_ok("fib_retracement manual down", "mt5_fib_retracement",
                    {"symbol": SYMBOL, "timeframe": "H1", "high": 161.0, "low": 160.0, "direction": "down"},
                    lambda d: d["direction"] == "down")
    await expect_ok("fib_expansion auto", "mt5_fib_expansion",
                    {"symbol": SYMBOL, "timeframe": "H1", "auto": True},
                    lambda d: len(d["levels"]) == 8)
    await expect_ok("fib_expansion manual", "mt5_fib_expansion",
                    {"symbol": SYMBOL, "timeframe": "H1", "p1": 160.0, "p2": 161.0, "p3": 160.5},
                    lambda d: any(abs(l["price"] - 161.5) < 1e-6 for l in d["levels"] if l["level"] == 1.0))
    await expect_ok("fib custom levels", "mt5_fib_retracement",
                    {"symbol": SYMBOL, "timeframe": "H1", "high": 161.0, "low": 160.0,
                     "direction": "up", "levels": [0, 1.272, 1.618]},
                    lambda d: len(d["levels"]) == 3)

    # --- 複合分析 ---
    await expect_ok("market_snapshot", "mt5_market_snapshot", {"symbol": SYMBOL, "timeframe": "H1"},
                    lambda d: d["trend"] in ("uptrend", "downtrend", "range", "unknown"))
    await expect_ok("analyze multi-TF", "mt5_analyze", {"symbol": SYMBOL},
                    lambda d: len(d["timeframes"]) == 3 and "bias" in d)
    await expect_ok("confluence", "mt5_confluence", {"symbol": SYMBOL, "timeframe": "H1"},
                    lambda d: "confluence_zones" in d)

    # --- エラー処理 ---
    await expect_err("invalid timeframe", "mt5_ohlcv",
                     {"symbol": SYMBOL, "timeframe": "X9", "count": 10}, "INVALID_ARGUMENT")
    await expect_err("invalid symbol", "mt5_symbol_info", {"symbol": "NOPE_XYZ"}, "INVALID_ARGUMENT")
    await expect_err("unknown indicator", "mt5_indicator",
                     {"symbol": SYMBOL, "timeframe": "H1", "name": "foobar"}, "INVALID_ARGUMENT")

    # --- 発注系 (ドライラン / 安全ガードのみ。実発注なし) ---
    await expect_ok("order_send dry-run (market)", "mt5_order_send",
                    {"symbol": SYMBOL, "side": "buy", "volume": 0.01, "type": "market"},
                    lambda d: d["dry_run"] is True and "preview" in d)
    await expect_ok("order_send dry-run (limit)", "mt5_order_send",
                    {"symbol": SYMBOL, "side": "buy", "volume": 0.01, "type": "limit", "price": 150.0},
                    lambda d: d["dry_run"] is True)
    await expect_err("limit without price", "mt5_order_send",
                     {"symbol": SYMBOL, "side": "buy", "volume": 0.01, "type": "limit"}, "INVALID_ARGUMENT")
    await expect_err("safety: lot over MAX_LOT", "mt5_order_send",
                     {"symbol": SYMBOL, "side": "buy", "volume": 5.0, "type": "market"}, "SAFETY_BLOCKED")
    await expect_err("safety: invalid side", "mt5_order_send",
                     {"symbol": SYMBOL, "side": "long", "volume": 0.01, "type": "market"}, "INVALID_ARGUMENT")
    await expect_ok("close_all dry-run", "mt5_close_all", {},
                    lambda d: (d.get("dry_run") is True) or (d.get("message") is not None))
    # ポジション変更は事前にチケット存在を確認 → INVALID_ARGUMENT
    await expect_err("position_modify bad ticket", "mt5_position_modify",
                     {"ticket": 999999999, "sl": 100.0}, "INVALID_ARGUMENT")
    # order_cancel は confirm 無しでドライランになり、preview で無効チケットを surface する
    await expect_ok("order_cancel bad ticket → dry-run preview", "mt5_order_cancel",
                    {"ticket": 999999999},
                    lambda d: d["dry_run"] is True and d["preview"]["retcode_name"] == "TRADE_RETCODE_INVALID")

    # 結果出力
    print("\n".join(results))
    print(f"\n===== RESULT: PASS={PASS}  FAIL={FAIL}  TOTAL={PASS + FAIL} =====")


if __name__ == "__main__":
    asyncio.run(main())
