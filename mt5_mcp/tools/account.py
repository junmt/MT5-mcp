"""ポジション・注文照会系ツール。仕様書 §5.5。"""

from __future__ import annotations

from datetime import datetime, timezone

from ..connection import last_error, mt
from ..utils.format import epoch_to_utc_iso, err, ok, to_jsonable


def _parse_dt(value: str) -> datetime:
    s = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _enrich_time(rows: list[dict]) -> list[dict]:
    for r in rows:
        for key in ("time", "time_setup", "time_done", "time_update"):
            if key in r and isinstance(r[key], (int, float)) and r[key] > 0:
                r[f"{key}_utc"] = epoch_to_utc_iso(r[key])
    return rows


def register(mcp) -> None:
    @mcp.tool()
    def mt5_positions(symbol: str | None = None) -> dict:
        """オープンポジション一覧。symbol 指定で絞り込み。"""
        try:
            m = mt()
            positions = m.positions_get(symbol=symbol) if symbol else m.positions_get()
            if positions is None:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"positions_get 失敗: {desc}", mt5_code=code)
            rows = _enrich_time([to_jsonable(p) for p in positions])
            return ok({"count": len(rows), "positions": rows})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_orders(symbol: str | None = None) -> dict:
        """未約定（待機）注文一覧。"""
        try:
            m = mt()
            orders = m.orders_get(symbol=symbol) if symbol else m.orders_get()
            if orders is None:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"orders_get 失敗: {desc}", mt5_code=code)
            rows = _enrich_time([to_jsonable(o) for o in orders])
            return ok({"count": len(rows), "orders": rows})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_history_deals(from_date: str, to_date: str, symbol: str | None = None) -> dict:
        """約定履歴。from_date/to_date は ISO8601。"""
        try:
            m = mt()
            deals = m.history_deals_get(_parse_dt(from_date), _parse_dt(to_date))
            if deals is None:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"history_deals_get 失敗: {desc}", mt5_code=code)
            rows = [to_jsonable(d) for d in deals]
            if symbol:
                rows = [r for r in rows if r.get("symbol") == symbol]
            return ok({"count": len(rows), "deals": _enrich_time(rows)})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_history_orders(from_date: str, to_date: str, symbol: str | None = None) -> dict:
        """注文履歴。from_date/to_date は ISO8601。"""
        try:
            m = mt()
            orders = m.history_orders_get(_parse_dt(from_date), _parse_dt(to_date))
            if orders is None:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"history_orders_get 失敗: {desc}", mt5_code=code)
            rows = [to_jsonable(o) for o in orders]
            if symbol:
                rows = [r for r in rows if r.get("symbol") == symbol]
            return ok({"count": len(rows), "orders": _enrich_time(rows)})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))
