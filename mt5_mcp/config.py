"""設定読み込み（環境変数 / .env）。仕様書 §4 に対応。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 未導入でも動作可能
    pass


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


@dataclass
class Config:
    # 接続
    path: str | None = field(default_factory=lambda: os.getenv("MT5_PATH") or None)
    login: int | None = None
    password: str | None = field(default_factory=lambda: os.getenv("MT5_PASSWORD") or None)
    server: str | None = field(default_factory=lambda: os.getenv("MT5_SERVER") or None)
    timeout: int = field(default_factory=lambda: _get_int("MT5_TIMEOUT", 60000))

    # 発注ガード（仕様書 §6）
    trade_enabled: bool = field(default_factory=lambda: _get_bool("MT5_TRADE_ENABLED", False))
    trade_confirm: bool = field(default_factory=lambda: _get_bool("MT5_TRADE_CONFIRM", True))
    max_lot: float = field(default_factory=lambda: _get_float("MT5_MAX_LOT", 1.0))
    max_slippage: int = field(default_factory=lambda: _get_int("MT5_MAX_SLIPPAGE", 20))
    magic: int = field(default_factory=lambda: _get_int("MT5_MAGIC", 20260610))

    allowed_symbols: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        login_raw = os.getenv("MT5_LOGIN")
        if login_raw and login_raw.strip():
            try:
                self.login = int(login_raw)
            except ValueError:
                self.login = None

        raw = os.getenv("MT5_ALLOWED_SYMBOLS", "*").strip()
        if raw in ("", "*"):
            self.allowed_symbols = []  # 空リスト = 全許可
        else:
            self.allowed_symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]

    def symbol_allowed(self, symbol: str) -> bool:
        if not self.allowed_symbols:
            return True
        return symbol.upper() in self.allowed_symbols


# モジュールレベルのシングルトン
CONFIG = Config()
