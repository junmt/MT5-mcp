"""MT5 初期化・ログイン・再接続・ライフサイクル管理。仕様書 §3.2。"""

from __future__ import annotations

import logging
import threading
import time

import MetaTrader5 as mt5

from .config import CONFIG

log = logging.getLogger("mt5_mcp.connection")

_lock = threading.Lock()
_initialized = False


class MT5Error(RuntimeError):
    """MT5 接続/操作に関する例外。"""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def last_error() -> tuple[int, str]:
    code, desc = mt5.last_error()
    return int(code), str(desc)


def _do_initialize() -> None:
    kwargs: dict = {"timeout": CONFIG.timeout}
    if CONFIG.path:
        kwargs["path"] = CONFIG.path
    if CONFIG.login:
        kwargs["login"] = CONFIG.login
    if CONFIG.password:
        kwargs["password"] = CONFIG.password
    if CONFIG.server:
        kwargs["server"] = CONFIG.server

    # path は第1引数（位置引数）として渡す必要がある
    path = kwargs.pop("path", None)
    if path:
        success = mt5.initialize(path, **kwargs)
    else:
        success = mt5.initialize(**kwargs)

    if not success:
        code, desc = last_error()
        raise MT5Error(f"MT5 initialize 失敗: {desc}", code)


def ensure_connected(max_retries: int = 3) -> None:
    """接続を保証する。未接続なら初期化、切断検知時は再接続する。"""
    global _initialized
    with _lock:
        # 既存接続が生きているか確認
        if _initialized:
            info = mt5.terminal_info()
            if info is not None and getattr(info, "connected", False):
                return
            # 切断 → 再初期化のため一旦 shutdown
            log.warning("MT5 接続が切れています。再接続します。")
            try:
                mt5.shutdown()
            except Exception:
                pass
            _initialized = False

        delay = 0.5
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                _do_initialize()
                _initialized = True
                log.info("MT5 接続成功 (attempt %d)", attempt)
                return
            except MT5Error as exc:
                last_exc = exc
                log.warning("接続失敗 (attempt %d/%d): %s", attempt, max_retries, exc)
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2

        assert last_exc is not None
        raise last_exc


def shutdown() -> None:
    global _initialized
    with _lock:
        if _initialized:
            try:
                mt5.shutdown()
            finally:
                _initialized = False


def mt() -> "mt5":
    """接続を保証した上で MetaTrader5 モジュールを返す。"""
    ensure_connected()
    return mt5
