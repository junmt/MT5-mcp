"""発注・取引系ツール。仕様書 §5.6, §6。

MT5_TRADE_ENABLED=true のときのみ登録される。
confirm=true が無い発注は order_check によるドライランに変換する（二段階確認）。
"""

from __future__ import annotations

import MetaTrader5 as mt5

from .. import safety
from ..config import CONFIG
from ..connection import last_error, mt
from ..utils.format import err, ok, to_jsonable
from ..utils.mapping import parse_order_type, retcode_name


def _filling_mode(symbol_info) -> int:
    """シンボルの許可する filling モードを選ぶ。"""
    mode = getattr(symbol_info, "filling_mode", 0)
    # filling_mode はビットフラグ。IOC を優先、無ければ FOK、最後に RETURN。
    if mode & 2:  # SYMBOL_FILLING_IOC
        return mt5.ORDER_FILLING_IOC
    if mode & 1:  # SYMBOL_FILLING_FOK
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def _send_or_check(m, request: dict, confirm: bool | None, action: str) -> dict:
    """confirm に応じて order_check(ドライラン) か order_send(実発注) を行う。"""
    safety.record(action, stage="request", request=request, confirm=bool(confirm))

    check = m.order_check(request)
    if check is None:
        code, desc = last_error()
        safety.record(action, stage="check_failed", mt5_code=code, desc=desc)
        return err("TRADE_ERROR", f"order_check 失敗: {desc}", mt5_code=code)

    check_d = to_jsonable(check)
    # order_check 自体の retcode が異常ならドライランでも警告
    preview = {
        "retcode": check_d.get("retcode"),
        "retcode_name": retcode_name(check.retcode),
        "comment": check_d.get("comment"),
        "balance": check_d.get("balance"),
        "margin": check_d.get("margin"),
        "margin_free": check_d.get("margin_free"),
        "margin_level": check_d.get("margin_level"),
        "request": request,
    }

    if not safety.is_confirmed(confirm):
        safety.record(action, stage="dry_run", retcode=check.retcode)
        return ok(
            {
                "dry_run": True,
                "message": "confirm=true を指定すると実発注します（これはプレビューです）。",
                "preview": preview,
            }
        )

    # order_check が通っていなければ実発注を止める
    if check.retcode != mt5.TRADE_RETCODE_DONE and check.retcode != 0:
        # 一部ブローカーは check で 0 以外を返すため margin 検証のみ重視
        if check.margin_free is not None and check.margin_free < 0:
            safety.record(action, stage="blocked_margin", retcode=check.retcode)
            return err("TRADE_ERROR", f"証拠金不足の可能性: {check.comment}", preview=preview)

    result = m.order_send(request)
    if result is None:
        code, desc = last_error()
        safety.record(action, stage="send_failed", mt5_code=code, desc=desc)
        return err("TRADE_ERROR", f"order_send 失敗: {desc}", mt5_code=code)

    result_d = to_jsonable(result)
    result_d["retcode_name"] = retcode_name(result.retcode)
    safety.record(action, stage="executed", retcode=result.retcode, order=result_d.get("order"), deal=result_d.get("deal"))

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return err(
            "TRADE_ERROR",
            f"発注が完了しませんでした: {retcode_name(result.retcode)} ({result.comment})",
            result=result_d,
        )
    return ok({"dry_run": False, "result": result_d})


def register(mcp) -> None:
    @mcp.tool()
    def mt5_order_send(
        symbol: str,
        side: str,
        volume: float,
        type: str = "market",
        price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "mt5-mcp",
        confirm: bool = False,
        deviation: int | None = None,
    ) -> dict:
        """新規注文（成行/指値/逆指値）。

        side: buy/sell, type: market/limit/stop/stop_limit。
        confirm 省略時はドライラン(order_check)。実発注は confirm=true。
        指値/逆指値は price 必須。
        """
        try:
            safety.require_trade_enabled()
            safety.check_symbol(symbol)
            safety.check_volume(volume)
            order_type = parse_order_type(side, type)
        except safety.SafetyError as exc:
            return err("SAFETY_BLOCKED", str(exc))
        except ValueError as exc:
            return err("INVALID_ARGUMENT", str(exc))

        try:
            m = mt()
            si = m.symbol_info(symbol)
            if si is None:
                return err("INVALID_ARGUMENT", f"シンボル {symbol} が見つかりません。")
            if not si.visible:
                m.symbol_select(symbol, True)
                si = m.symbol_info(symbol)

            ti = m.terminal_info()
            try:
                safety.check_terminal_trade_allowed(ti)
            except safety.SafetyError as exc:
                return err("SAFETY_BLOCKED", str(exc))

            is_market = type.strip().lower() == "market"
            if is_market:
                tick = m.symbol_info_tick(symbol)
                exec_price = tick.ask if side.lower() == "buy" else tick.bid
                action = mt5.TRADE_ACTION_DEAL
            else:
                if price is None:
                    return err("INVALID_ARGUMENT", f"{type} 注文には price が必要です。")
                exec_price = float(price)
                action = mt5.TRADE_ACTION_PENDING

            dev = deviation if deviation is not None else CONFIG.max_slippage
            dev = min(int(dev), CONFIG.max_slippage)  # 上限を強制

            request = {
                "action": action,
                "symbol": symbol,
                "volume": float(volume),
                "type": order_type,
                "price": round(float(exec_price), si.digits),
                "deviation": dev,
                "magic": CONFIG.magic,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": _filling_mode(si),
            }
            if sl is not None:
                request["sl"] = round(float(sl), si.digits)
            if tp is not None:
                request["tp"] = round(float(tp), si.digits)

            return _send_or_check(m, request, confirm, "order_send")
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_position_close(ticket: int, volume: float | None = None, confirm: bool = False) -> dict:
        """ポジションを決済する（volume 省略で全決済、指定で一部決済）。"""
        try:
            safety.require_trade_enabled()
        except safety.SafetyError as exc:
            return err("SAFETY_BLOCKED", str(exc))
        try:
            m = mt()
            pos = m.positions_get(ticket=ticket)
            if not pos:
                return err("INVALID_ARGUMENT", f"ポジション {ticket} が見つかりません。")
            p = pos[0]
            si = m.symbol_info(p.symbol)
            tick = m.symbol_info_tick(p.symbol)
            # 反対売買
            if p.type == mt5.POSITION_TYPE_BUY:
                close_type = mt5.ORDER_TYPE_SELL
                close_price = tick.bid
            else:
                close_type = mt5.ORDER_TYPE_BUY
                close_price = tick.ask

            close_vol = float(volume) if volume else float(p.volume)
            try:
                safety.check_volume(close_vol)
            except safety.SafetyError as exc:
                return err("SAFETY_BLOCKED", str(exc))

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": close_vol,
                "type": close_type,
                "position": int(ticket),
                "price": round(float(close_price), si.digits),
                "deviation": CONFIG.max_slippage,
                "magic": CONFIG.magic,
                "comment": "mt5-mcp-close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": _filling_mode(si),
            }
            return _send_or_check(m, request, confirm, "position_close")
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_position_modify(ticket: int, sl: float | None = None, tp: float | None = None, confirm: bool = False) -> dict:
        """ポジションの SL/TP を変更する。"""
        try:
            safety.require_trade_enabled()
        except safety.SafetyError as exc:
            return err("SAFETY_BLOCKED", str(exc))
        try:
            m = mt()
            pos = m.positions_get(ticket=ticket)
            if not pos:
                return err("INVALID_ARGUMENT", f"ポジション {ticket} が見つかりません。")
            p = pos[0]
            si = m.symbol_info(p.symbol)
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": p.symbol,
                "position": int(ticket),
                "sl": round(float(sl), si.digits) if sl is not None else p.sl,
                "tp": round(float(tp), si.digits) if tp is not None else p.tp,
                "magic": CONFIG.magic,
            }
            return _send_or_check(m, request, confirm, "position_modify")
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_order_modify(
        ticket: int,
        price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        confirm: bool = False,
    ) -> dict:
        """待機注文の価格 / SL / TP を変更する。"""
        try:
            safety.require_trade_enabled()
        except safety.SafetyError as exc:
            return err("SAFETY_BLOCKED", str(exc))
        try:
            m = mt()
            orders = m.orders_get(ticket=ticket)
            if not orders:
                return err("INVALID_ARGUMENT", f"注文 {ticket} が見つかりません。")
            o = orders[0]
            si = m.symbol_info(o.symbol)
            request = {
                "action": mt5.TRADE_ACTION_MODIFY,
                "order": int(ticket),
                "symbol": o.symbol,
                "price": round(float(price), si.digits) if price is not None else o.price_open,
                "sl": round(float(sl), si.digits) if sl is not None else o.sl,
                "tp": round(float(tp), si.digits) if tp is not None else o.tp,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            return _send_or_check(m, request, confirm, "order_modify")
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_order_cancel(ticket: int, confirm: bool = False) -> dict:
        """待機注文を取り消す。"""
        try:
            safety.require_trade_enabled()
        except safety.SafetyError as exc:
            return err("SAFETY_BLOCKED", str(exc))
        try:
            m = mt()
            request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
            return _send_or_check(m, request, confirm, "order_cancel")
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_close_all(symbol: str | None = None, confirm: bool = False) -> dict:
        """条件一致ポジションを一括決済する。symbol 省略で全ポジション。

        confirm 省略時は対象一覧のプレビューのみ返す。
        """
        try:
            safety.require_trade_enabled()
        except safety.SafetyError as exc:
            return err("SAFETY_BLOCKED", str(exc))
        try:
            m = mt()
            positions = m.positions_get(symbol=symbol) if symbol else m.positions_get()
            if not positions:
                return ok({"closed": [], "message": "対象ポジションがありません。"})

            targets = [{"ticket": p.ticket, "symbol": p.symbol, "volume": float(p.volume)} for p in positions]
            if not safety.is_confirmed(confirm):
                return ok(
                    {
                        "dry_run": True,
                        "message": "confirm=true で以下を全決済します。",
                        "targets": targets,
                        "count": len(targets),
                    }
                )

            results = []
            for p in positions:
                si = m.symbol_info(p.symbol)
                tick = m.symbol_info_tick(p.symbol)
                if p.type == mt5.POSITION_TYPE_BUY:
                    close_type, close_price = mt5.ORDER_TYPE_SELL, tick.bid
                else:
                    close_type, close_price = mt5.ORDER_TYPE_BUY, tick.ask
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": p.symbol,
                    "volume": float(p.volume),
                    "type": close_type,
                    "position": int(p.ticket),
                    "price": round(float(close_price), si.digits),
                    "deviation": CONFIG.max_slippage,
                    "magic": CONFIG.magic,
                    "comment": "mt5-mcp-closeall",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": _filling_mode(si),
                }
                safety.record("close_all", stage="request", ticket=int(p.ticket))
                res = m.order_send(request)
                rd = to_jsonable(res) if res else None
                if rd:
                    rd["retcode_name"] = retcode_name(res.retcode)
                results.append({"ticket": int(p.ticket), "result": rd})
                safety.record("close_all", stage="executed", ticket=int(p.ticket), retcode=getattr(res, "retcode", None))
            return ok({"dry_run": False, "results": results, "count": len(results)})
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))
