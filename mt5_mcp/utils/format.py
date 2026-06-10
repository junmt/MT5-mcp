"""数値整形・JSON シリアライズ補助。仕様書 §8 に対応。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np


def to_jsonable(obj: Any) -> Any:
    """numpy / namedtuple / datetime などを JSON 化可能な素の型へ再帰変換する。"""
    # MT5 の戻り値（namedtuple）は _asdict を持つ
    if hasattr(obj, "_asdict"):
        return to_jsonable(obj._asdict())

    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]

    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]

    if isinstance(obj, np.generic):
        return obj.item()

    if isinstance(obj, datetime):
        return obj.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    return obj


def epoch_to_utc_iso(seconds: float) -> str:
    """MT5 のエポック秒（UTC）を ISO8601(Z) 文字列へ。"""
    dt = datetime.fromtimestamp(float(seconds), tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def round_price(value: float, digits: int) -> float:
    return round(float(value), int(digits))


def ok(data: Any) -> dict:
    return {"ok": True, "data": to_jsonable(data)}


def err(code: str, message: str, **extra: Any) -> dict:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if extra:
        payload["error"].update(to_jsonable(extra))
    return payload
