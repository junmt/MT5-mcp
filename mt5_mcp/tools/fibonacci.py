"""フィボナッチ系ツール。仕様書 §5.4.1。

スイング（高値/安値）を基準にリトレースメント/エクスパンション水準を算出する。
手動指定（価格直接）と自動検出（ZigZag 風スイング）の両対応。
"""

from __future__ import annotations

import pandas as pd

from ..connection import last_error, mt
from ..utils.format import epoch_to_utc_iso, err, ok
from ..utils.mapping import parse_timeframe

_MAX_BARS = 5000

DEFAULT_RETRACEMENT = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
DEFAULT_EXPANSION = [0.0, 0.382, 0.618, 1.0, 1.382, 1.618, 2.0, 2.618]


def _fetch_df(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    tf = parse_timeframe(timeframe)
    count = max(10, min(int(count), _MAX_BARS))
    m = mt()
    rates = m.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        code, desc = last_error()
        raise RuntimeError(f"バー取得失敗: {desc} (code={code})")
    return pd.DataFrame(rates)


def _digits(symbol: str) -> int:
    info = mt().symbol_info(symbol)
    return int(info.digits) if info else 5


def detect_swings(df: pd.DataFrame, depth: int = 5) -> list[dict]:
    """ZigZag 風のスイング点を検出する。

    各バーが前後 depth 本の中で極大(高値)/極小(安値)であれば pivot とみなし、
    高値・安値が交互になるよう整理して返す。返り値は時系列順。
    """
    highs = df["high"].values
    lows = df["low"].values
    times = df["time"].values
    n = len(df)
    pivots: list[dict] = []

    for i in range(depth, n - depth):
        window_hi = highs[i - depth : i + depth + 1]
        window_lo = lows[i - depth : i + depth + 1]
        is_high = highs[i] == window_hi.max()
        is_low = lows[i] == window_lo.min()
        if is_high and not is_low:
            pivots.append({"index": i, "type": "high", "price": float(highs[i]), "time": times[i]})
        elif is_low and not is_high:
            pivots.append({"index": i, "type": "low", "price": float(lows[i]), "time": times[i]})

    # 同種連続を間引き（高値同士なら高い方、安値同士なら安い方を残す）
    cleaned: list[dict] = []
    for p in pivots:
        if cleaned and cleaned[-1]["type"] == p["type"]:
            prev = cleaned[-1]
            if p["type"] == "high":
                if p["price"] >= prev["price"]:
                    cleaned[-1] = p
            else:
                if p["price"] <= prev["price"]:
                    cleaned[-1] = p
        else:
            cleaned.append(p)
    return cleaned


def _swings_jsonable(swings: list[dict]) -> list[dict]:
    return [
        {
            "type": s["type"],
            "price": s["price"],
            "time": epoch_to_utc_iso(s["time"]),
            "index": int(s["index"]),
        }
        for s in swings
    ]


def _current_price(symbol: str) -> float | None:
    tick = mt().symbol_info_tick(symbol)
    if tick is None:
        return None
    return float((tick.bid + tick.ask) / 2)


def _zone_of(price: float, levels: list[dict]) -> str | None:
    """現在価格がどの水準帯にあるかを "0.382-0.5" 形式で返す。"""
    if price is None or len(levels) < 2:
        return None
    ordered = sorted(levels, key=lambda x: x["price"])
    for a, b in zip(ordered, ordered[1:]):
        lo, hi = a["price"], b["price"]
        if lo <= price <= hi:
            return f"{a['level']}-{b['level']}"
    if price < ordered[0]["price"]:
        return f"<{ordered[0]['level']}"
    return f">{ordered[-1]['level']}"


def register(mcp) -> None:
    @mcp.tool()
    def mt5_swing_points(
        symbol: str,
        timeframe: str,
        count: int = 300,
        depth: int = 5,
    ) -> dict:
        """スイング高値・安値（ZigZag 相当）を検出する。

        depth: ピボット判定の左右本数（大きいほど大きな波のみ検出）。
        """
        try:
            df = _fetch_df(symbol, timeframe, count)
            swings = detect_swings(df, depth)
            return ok(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.upper(),
                    "depth": depth,
                    "count": len(swings),
                    "swings": _swings_jsonable(swings),
                }
            )
        except ValueError as exc:
            return err("INVALID_ARGUMENT", str(exc))
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_fib_retracement(
        symbol: str,
        timeframe: str,
        high: float | None = None,
        low: float | None = None,
        direction: str | None = None,
        auto: bool = False,
        levels: list[float] | None = None,
        count: int = 300,
        depth: int = 5,
    ) -> dict:
        """フィボナッチ・リトレースメント水準を算出する。

        手動: high, low, direction(up=安値→高値の上昇波 / down=高値→安値の下落波)。
        自動: auto=true で直近スイング2点から基点を決定。
        levels 省略時は [0,0.236,0.382,0.5,0.618,0.786,1.0]。延長水準(1.272 等)も指定可。
        """
        lv = levels if levels else DEFAULT_RETRACEMENT
        try:
            digits = _digits(symbol)
            used_swings = None

            if auto or high is None or low is None:
                df = _fetch_df(symbol, timeframe, count)
                swings = detect_swings(df, depth)
                if len(swings) < 2:
                    return err("INVALID_ARGUMENT", "スイングを2点以上検出できませんでした。high/low を手動指定してください。")
                a, b = swings[-2], swings[-1]
                used_swings = _swings_jsonable([a, b])
                # b が高値なら上昇波(up)、安値なら下落波(down)
                if b["type"] == "high":
                    direction = "up"
                    high, low = b["price"], a["price"]
                else:
                    direction = "down"
                    high, low = a["price"], b["price"]
            else:
                direction = (direction or "up").lower()

            high = float(high)
            low = float(low)
            diff = high - low
            if diff <= 0:
                return err("INVALID_ARGUMENT", "high は low より大きい必要があります。")

            # up: 高値(=0) から下方向に押し目を測る → price = high - ratio*diff
            # down: 安値(=0) から上方向に戻りを測る → price = low + ratio*diff
            out_levels = []
            for r in lv:
                if direction == "down":
                    price = low + r * diff
                else:
                    price = high - r * diff
                out_levels.append({"level": r, "price": round(price, digits)})

            cur = _current_price(symbol)
            return ok(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.upper(),
                    "method": "retracement",
                    "direction": direction,
                    "anchors": {"high": round(high, digits), "low": round(low, digits)},
                    "levels": out_levels,
                    "current_price": round(cur, digits) if cur is not None else None,
                    "current_zone": _zone_of(cur, out_levels),
                    "auto_swings": used_swings,
                }
            )
        except ValueError as exc:
            return err("INVALID_ARGUMENT", str(exc))
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_fib_expansion(
        symbol: str,
        timeframe: str,
        p1: float | None = None,
        p2: float | None = None,
        p3: float | None = None,
        auto: bool = False,
        levels: list[float] | None = None,
        count: int = 300,
        depth: int = 5,
    ) -> dict:
        """フィボナッチ・エクスパンション(エクステンション)水準を算出する（3点法）。

        手動: p1(始点), p2(波の終点), p3(押し/戻りの起点)。
        自動: auto=true で直近スイング3点(A-B-C)を使用。
        投影: price = p3 + level * (p2 - p1)。
        levels 省略時は [0,0.382,0.618,1.0,1.382,1.618,2.0,2.618]。
        """
        lv = levels if levels else DEFAULT_EXPANSION
        try:
            digits = _digits(symbol)
            used_swings = None

            if auto or p1 is None or p2 is None or p3 is None:
                df = _fetch_df(symbol, timeframe, count)
                swings = detect_swings(df, depth)
                if len(swings) < 3:
                    return err("INVALID_ARGUMENT", "スイングを3点以上検出できませんでした。p1/p2/p3 を手動指定してください。")
                a, b, c = swings[-3], swings[-2], swings[-1]
                used_swings = _swings_jsonable([a, b, c])
                p1, p2, p3 = a["price"], b["price"], c["price"]

            p1, p2, p3 = float(p1), float(p2), float(p3)
            wave = p2 - p1
            if wave == 0:
                return err("INVALID_ARGUMENT", "p1 と p2 が同値です。")

            out_levels = []
            for r in lv:
                price = p3 + r * wave
                out_levels.append({"level": r, "price": round(price, digits)})

            cur = _current_price(symbol)
            return ok(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.upper(),
                    "method": "expansion",
                    "direction": "up" if wave > 0 else "down",
                    "anchors": {
                        "p1": round(p1, digits),
                        "p2": round(p2, digits),
                        "p3": round(p3, digits),
                    },
                    "levels": out_levels,
                    "current_price": round(cur, digits) if cur is not None else None,
                    "auto_swings": used_swings,
                }
            )
        except ValueError as exc:
            return err("INVALID_ARGUMENT", str(exc))
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))
