"""マーケットデータ系ツール。仕様書 §5.1, §5.2。"""

from __future__ import annotations

from ..connection import last_error, mt
from ..utils.format import epoch_to_utc_iso, err, ok, to_jsonable


def register(mcp) -> None:
    @mcp.tool()
    def mt5_health_check() -> dict:
        """MT5 ターミナルとの接続状態・バージョン情報を返す。"""
        try:
            m = mt()
            ti = m.terminal_info()
            ver = m.version()
            return ok(
                {
                    "connected": bool(getattr(ti, "connected", False)) if ti else False,
                    "trade_allowed": bool(getattr(ti, "trade_allowed", False)) if ti else False,
                    "version": to_jsonable(ver),
                    "terminal": to_jsonable(ti),
                }
            )
        except Exception as exc:  # noqa: BLE001
            code, desc = last_error()
            return err("CONNECTION_ERROR", f"{exc} ({desc})", mt5_code=code)

    @mcp.tool()
    def mt5_account_info() -> dict:
        """口座情報（残高・有効証拠金・証拠金・レバレッジ・通貨など）を返す。"""
        try:
            info = mt().account_info()
            if info is None:
                code, desc = last_error()
                return err("CONNECTION_ERROR", f"account_info 取得失敗: {desc}", mt5_code=code)
            return ok(info)
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_terminal_info() -> dict:
        """ターミナルの設定情報（取引許可・接続状態・パス等）を返す。"""
        try:
            info = mt().terminal_info()
            return ok(info)
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_symbols_list(group: str | None = None, limit: int = 200) -> dict:
        """利用可能シンボル一覧。group はワイルドカードフィルタ（例 "*USD*"）。"""
        try:
            m = mt()
            symbols = m.symbols_get(group) if group else m.symbols_get()
            if symbols is None:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"symbols_get 失敗: {desc}", mt5_code=code)
            names = [s.name for s in symbols]
            return ok({"count": len(names), "symbols": names[: max(0, limit)]})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_symbol_info(symbol: str) -> dict:
        """シンボル詳細（スプレッド・桁数・ロット制限・取引モード等）。"""
        try:
            m = mt()
            info = m.symbol_info(symbol)
            if info is None:
                code, desc = last_error()
                return err("INVALID_ARGUMENT", f"シンボル {symbol} が見つかりません: {desc}", mt5_code=code)
            d = to_jsonable(info)
            # よく使う項目を要約として併記
            summary = {
                "symbol": d.get("name"),
                "digits": d.get("digits"),
                "point": d.get("point"),
                "spread": d.get("spread"),
                "contract_size": d.get("trade_contract_size"),
                "volume_min": d.get("volume_min"),
                "volume_max": d.get("volume_max"),
                "volume_step": d.get("volume_step"),
                "trade_mode": d.get("trade_mode"),
            }
            return ok({"summary": summary, "full": d})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_quote(symbol: str) -> dict:
        """現在の気配（bid/ask/last/スプレッド/時刻）を返す。"""
        try:
            m = mt()
            if not m.symbol_select(symbol, True):
                code, desc = last_error()
                return err("INVALID_ARGUMENT", f"シンボル {symbol} を選択できません: {desc}", mt5_code=code)
            tick = m.symbol_info_tick(symbol)
            si = m.symbol_info(symbol)
            if tick is None or si is None:
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"気配取得失敗: {desc}", mt5_code=code)
            digits = si.digits
            spread_pts = round((tick.ask - tick.bid) / si.point) if si.point else None
            return ok(
                {
                    "symbol": symbol,
                    "bid": round(tick.bid, digits),
                    "ask": round(tick.ask, digits),
                    "last": round(tick.last, digits),
                    "spread_points": spread_pts,
                    "volume": tick.volume,
                    "time_utc": epoch_to_utc_iso(tick.time),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_market_depth(symbol: str) -> dict:
        """板情報(DOM)を返す。ブローカーが DOM 配信する銘柄のみ有効。"""
        try:
            m = mt()
            if not m.market_book_add(symbol):
                code, desc = last_error()
                return err("INTERNAL_ERROR", f"板購読に失敗: {desc}", mt5_code=code)
            try:
                book = m.market_book_get(symbol)
            finally:
                m.market_book_release(symbol)
            if book is None:
                return err("INTERNAL_ERROR", "板情報が空です（DOM 非対応の可能性）。")
            bids, asks = [], []
            for item in book:
                d = to_jsonable(item)
                # type: 0=sell(ask), 1=buy(bid) … BOOK_TYPE 定数に準拠
                row = {"price": d.get("price"), "volume": d.get("volume")}
                if d.get("type") in (1, 3):  # BUY / BUY_MARKET
                    bids.append(row)
                else:
                    asks.append(row)
            return ok({"symbol": symbol, "bids": bids, "asks": asks})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))
