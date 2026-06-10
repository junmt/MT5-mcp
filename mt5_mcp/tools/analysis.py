"""複合分析系（高水準）ツール。仕様書 §5.7。"""

from __future__ import annotations

from ..connection import last_error, mt
from ..utils.format import epoch_to_utc_iso, err, ok
from . import fibonacci as fib
from . import indicators as ind


def _trend_from(close_now: float, sma_fast: float | None, sma_slow: float | None) -> str:
    if sma_fast is None or sma_slow is None:
        return "unknown"
    if close_now > sma_fast > sma_slow:
        return "uptrend"
    if close_now < sma_fast < sma_slow:
        return "downtrend"
    return "range"


def register(mcp) -> None:
    @mcp.tool()
    def mt5_market_snapshot(symbol: str, timeframe: str = "H1") -> dict:
        """気配・スプレッド・主要指標・直近トレンドをまとめて返す。"""
        try:
            m = mt()
            si = m.symbol_info(symbol)
            tick = m.symbol_info_tick(symbol)
            if si is None or tick is None:
                code, desc = last_error()
                return err("INVALID_ARGUMENT", f"{symbol} の情報取得失敗: {desc}", mt5_code=code)

            df = ind._fetch_df(symbol, timeframe, 200)
            close = float(df["close"].iloc[-1])
            ema20 = ind._compute(df, "ema", {"period": 20})["value"]
            ema50 = ind._compute(df, "ema", {"period": 50})["value"]
            rsi = ind._compute(df, "rsi", {"period": 14})["value"]
            atr = ind._compute(df, "atr", {"period": 14})["value"]
            macd = ind._compute(df, "macd", {})

            digits = si.digits
            return ok(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.upper(),
                    "quote": {
                        "bid": round(tick.bid, digits),
                        "ask": round(tick.ask, digits),
                        "spread_points": round((tick.ask - tick.bid) / si.point) if si.point else None,
                        "time_utc": epoch_to_utc_iso(tick.time),
                    },
                    "indicators": {
                        "ema20": round(ema20, digits) if ema20 else None,
                        "ema50": round(ema50, digits) if ema50 else None,
                        "rsi14": round(rsi, 2) if rsi else None,
                        "atr14": round(atr, digits) if atr else None,
                        "macd": macd,
                    },
                    "trend": _trend_from(close, ema20, ema50),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_analyze(symbol: str, timeframes: list[str] | None = None) -> dict:
        """複数タイムフレームのトレンド/モメンタムを要約し所見を生成する。"""
        tfs = timeframes or ["H4", "H1", "M15"]
        try:
            rows = []
            for tf in tfs:
                df = ind._fetch_df(symbol, tf, 200)
                close = float(df["close"].iloc[-1])
                ema20 = ind._compute(df, "ema", {"period": 20})["value"]
                ema50 = ind._compute(df, "ema", {"period": 50})["value"]
                rsi = ind._compute(df, "rsi", {"period": 14})["value"]
                trend = _trend_from(close, ema20, ema50)
                momentum = "neutral"
                if rsi is not None:
                    if rsi >= 70:
                        momentum = "overbought"
                    elif rsi <= 30:
                        momentum = "oversold"
                    elif rsi > 55:
                        momentum = "bullish"
                    elif rsi < 45:
                        momentum = "bearish"
                rows.append(
                    {"timeframe": tf.upper(), "trend": trend, "rsi14": round(rsi, 2) if rsi else None, "momentum": momentum}
                )

            trends = [r["trend"] for r in rows]
            if all(t == "uptrend" for t in trends):
                bias = "強い上昇バイアス（全TFで上昇）"
            elif all(t == "downtrend" for t in trends):
                bias = "強い下落バイアス（全TFで下落）"
            elif trends.count("uptrend") > trends.count("downtrend"):
                bias = "上昇寄り（上位足優勢）"
            elif trends.count("downtrend") > trends.count("uptrend"):
                bias = "下落寄り（上位足優勢）"
            else:
                bias = "方向感に乏しい（レンジ/混在）"

            return ok({"symbol": symbol, "timeframes": rows, "bias": bias})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_confluence(
        symbol: str,
        timeframe: str = "H1",
        tolerance_atr: float = 0.5,
        depth: int = 5,
    ) -> dict:
        """フィボ水準・直近スイング・移動平均を重ね合わせ、注目価格帯を抽出する。

        tolerance_atr: ATR の何倍以内に複数要素が集まればコンフルエンスとみなすか。
        """
        try:
            df = fib._fetch_df(symbol, timeframe, 300)
            digits = fib._digits(symbol)
            atr = ind._compute(df, "atr", {"period": 14})["value"] or 0.0
            tol = atr * tolerance_atr if atr else 0.0

            # 候補価格レベルを収集
            levels: list[dict] = []
            swings = fib.detect_swings(df, depth)
            if len(swings) >= 2:
                a, b = swings[-2], swings[-1]
                if b["type"] == "high":
                    hi, lo, direction = b["price"], a["price"], "up"
                else:
                    hi, lo, direction = a["price"], b["price"], "down"
                diff = hi - lo
                if diff > 0:
                    for r in fib.DEFAULT_RETRACEMENT:
                        price = (lo + r * diff) if direction == "down" else (hi - r * diff)
                        levels.append({"price": round(price, digits), "source": f"fib_{r}"})

            for s in swings[-6:]:
                levels.append({"price": round(s["price"], digits), "source": f"swing_{s['type']}"})

            ema20 = ind._compute(df, "ema", {"period": 20})["value"]
            ema50 = ind._compute(df, "ema", {"period": 50})["value"]
            if ema20:
                levels.append({"price": round(ema20, digits), "source": "ema20"})
            if ema50:
                levels.append({"price": round(ema50, digits), "source": "ema50"})

            # クラスタリング（tol 以内をまとめる）
            levels.sort(key=lambda x: x["price"])
            clusters: list[dict] = []
            for lvl in levels:
                if clusters and abs(lvl["price"] - clusters[-1]["center"]) <= tol:
                    c = clusters[-1]
                    c["members"].append(lvl)
                    c["center"] = round(sum(m["price"] for m in c["members"]) / len(c["members"]), digits)
                else:
                    clusters.append({"center": lvl["price"], "members": [lvl]})

            confluences = [
                {
                    "price": c["center"],
                    "strength": len(c["members"]),
                    "sources": [m["source"] for m in c["members"]],
                }
                for c in clusters
                if len(c["members"]) >= 2
            ]
            confluences.sort(key=lambda x: x["strength"], reverse=True)

            tick = mt().symbol_info_tick(symbol)
            cur = round((tick.bid + tick.ask) / 2, digits) if tick else None
            return ok(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.upper(),
                    "current_price": cur,
                    "atr14": round(atr, digits) if atr else None,
                    "tolerance": round(tol, digits),
                    "confluence_zones": confluences,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))
