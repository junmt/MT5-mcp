"""発注ガード（多層防御）と監査ログ。仕様書 §6。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import CONFIG

# 監査ログ（発注系の全操作をローカルに記録）
_AUDIT_DIR = Path(os.getenv("MT5_LOG_DIR") or (Path.home() / ".mt5_mcp"))
_AUDIT_FILE = _AUDIT_DIR / "trade_audit.log"

audit_log = logging.getLogger("mt5_mcp.audit")
if not audit_log.handlers:
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_AUDIT_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        audit_log.addHandler(handler)
        audit_log.setLevel(logging.INFO)
    except Exception:
        # ファイルに書けない環境でも本体は動かす
        pass


class SafetyError(RuntimeError):
    """安全制約違反。"""


def record(action: str, **fields) -> None:
    """発注関連操作を監査ログに JSON 1 行で記録する。"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        **fields,
    }
    try:
        audit_log.info(json.dumps(entry, ensure_ascii=False, default=str))
    except Exception:
        pass


def require_trade_enabled() -> None:
    """発注マスタースイッチ。無効なら拒否。"""
    if not CONFIG.trade_enabled:
        raise SafetyError(
            "発注機能は無効です。環境変数 MT5_TRADE_ENABLED=true で有効化してください。"
        )


def check_symbol(symbol: str) -> None:
    if not CONFIG.symbol_allowed(symbol):
        raise SafetyError(
            f"シンボル {symbol} は発注ホワイトリスト(MT5_ALLOWED_SYMBOLS)に含まれていません。"
        )


def check_volume(volume: float) -> None:
    if volume is None or volume <= 0:
        raise SafetyError(f"ロット数が不正です: {volume}")
    if volume > CONFIG.max_lot:
        raise SafetyError(
            f"ロット {volume} が上限 MT5_MAX_LOT={CONFIG.max_lot} を超えています。"
        )


def check_terminal_trade_allowed(terminal_info) -> None:
    if terminal_info is None or not getattr(terminal_info, "trade_allowed", False):
        raise SafetyError(
            "ターミナルでアルゴリズム取引が許可されていません"
            "（MT5: ツール→オプション→エキスパートアドバイザー）。"
        )


def is_confirmed(confirm: bool | None) -> bool:
    """二段階確認。confirm=True かつ（確認要求が無効なら常に True）。"""
    if not CONFIG.trade_confirm:
        return True
    return bool(confirm)
