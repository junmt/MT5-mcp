"""タイムフレーム / 注文種別の文字列⇔MT5定数 変換。仕様書 §5.3, §5.6。"""

from __future__ import annotations

import MetaTrader5 as mt5

TIMEFRAMES: dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M2": mt5.TIMEFRAME_M2,
    "M3": mt5.TIMEFRAME_M3,
    "M5": mt5.TIMEFRAME_M5,
    "M10": mt5.TIMEFRAME_M10,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H2": mt5.TIMEFRAME_H2,
    "H4": mt5.TIMEFRAME_H4,
    "H6": mt5.TIMEFRAME_H6,
    "H8": mt5.TIMEFRAME_H8,
    "H12": mt5.TIMEFRAME_H12,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


def parse_timeframe(name: str) -> int:
    key = str(name).strip().upper()
    if key not in TIMEFRAMES:
        raise ValueError(
            f"未知の timeframe: {name!r}. 利用可能: {', '.join(TIMEFRAMES)}"
        )
    return TIMEFRAMES[key]


# 注文種別: (side, type) -> ORDER_TYPE 定数
ORDER_TYPES: dict[tuple[str, str], int] = {
    ("buy", "market"): mt5.ORDER_TYPE_BUY,
    ("sell", "market"): mt5.ORDER_TYPE_SELL,
    ("buy", "limit"): mt5.ORDER_TYPE_BUY_LIMIT,
    ("sell", "limit"): mt5.ORDER_TYPE_SELL_LIMIT,
    ("buy", "stop"): mt5.ORDER_TYPE_BUY_STOP,
    ("sell", "stop"): mt5.ORDER_TYPE_SELL_STOP,
    ("buy", "stop_limit"): mt5.ORDER_TYPE_BUY_STOP_LIMIT,
    ("sell", "stop_limit"): mt5.ORDER_TYPE_SELL_STOP_LIMIT,
}


def parse_order_type(side: str, otype: str) -> int:
    key = (str(side).strip().lower(), str(otype).strip().lower())
    if key not in ORDER_TYPES:
        raise ValueError(
            f"未知の注文種別: side={side!r}, type={otype!r}. "
            f"side は buy/sell, type は market/limit/stop/stop_limit"
        )
    return ORDER_TYPES[key]


def retcode_name(code: int) -> str:
    """TRADE_RETCODE_* の名称を逆引き（見つからなければ番号文字列）。"""
    for attr in dir(mt5):
        if attr.startswith("TRADE_RETCODE_") and getattr(mt5, attr) == code:
            return attr
    return str(code)
