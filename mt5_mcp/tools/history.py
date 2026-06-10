"""ヒストリカルデータ系ツール。仕様書 §5.3。"""

from __future__ import annotations

from datetime import datetime, timezone

import MetaTrader5 as mt5

from ..connection import last_error, mt
from ..utils.format import epoch_to_utc_iso, err, ok, to_jsonable
from ..utils.mapping import parse_timeframe

_MAX_BARS = 5000


def _parse_dt(value: str) -> datetime:
    """ISO8601 文字列を UTC datetime に。"""
    s = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rates_to_bars(rates) -> list[dict]:
    bars = []
    for r in rates:
        bars.append(
            {
                "time": epoch_to_utc_iso(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["tick_volume"]),
                "spread": int(r["spread"]),
            }
        )
    return bars


def register(mcp) -> None:
    @mcp.tool()
    def mt5_ohlcv(
        symbol: str,
        timeframe: str,
        count: int = 100,
        from_date: str | None = None,
        to_date: str | None = None,
        full: bool = False,
    ) -> dict:
        """ローソク足(OHLCV)を取得する。

        既定は要約(summary)のみ。全足が必要な場合は full=true。
        from_date/to_date(ISO8601) を指定すると期間取得、無ければ直近 count 本。
        count 上限は 5000。
        """
        try:
            tf = parse_timeframe(timeframe)
        except ValueError as exc:
            return err("INVALID_ARGUMENT", str(exc))

        count = max(1, min(int(count), _MAX_BARS))
        try:
            m = mt()
            if from_date and to_date:
                rates = m.copy_rates_range(symbol, tf, _parse_dt(from_date), _parse_dt(to_date))
            elif from_date:
                rates = m.copy_rates_from(symbol, tf, _parse_dt(from_date), count)
            else:
                rates = m.copy_rates_from_pos(symbol, tf, 0, count)

            if rates is None or len(rates) == 0:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"バー取得失敗: {desc}", mt5_code=code)

            bars = _rates_to_bars(rates)
            highs = [b["high"] for b in bars]
            lows = [b["low"] for b in bars]
            summary = {
                "symbol": symbol,
                "timeframe": timeframe.upper(),
                "bars_count": len(bars),
                "range_high": max(highs),
                "range_low": min(lows),
                "first_time": bars[0]["time"],
                "last_time": bars[-1]["time"],
                "last_bar": bars[-1],
            }
            result = {"summary": summary}
            if full:
                result["bars"] = bars
            return ok(result)
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_ticks(symbol: str, from_date: str, count: int = 100) -> dict:
        """ティック履歴を取得する。from_date(ISO8601) から count 件。"""
        count = max(1, min(int(count), _MAX_BARS))
        try:
            m = mt()
            ticks = m.copy_ticks_from(symbol, _parse_dt(from_date), count, mt5.COPY_TICKS_ALL)
            if ticks is None or len(ticks) == 0:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"ティック取得失敗: {desc}", mt5_code=code)
            out = []
            for t in ticks:
                out.append(
                    {
                        "time": epoch_to_utc_iso(t["time"]),
                        "bid": float(t["bid"]),
                        "ask": float(t["ask"]),
                        "last": float(t["last"]),
                        "volume": int(t["volume"]),
                    }
                )
            return ok({"symbol": symbol, "count": len(out), "ticks": out})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))
