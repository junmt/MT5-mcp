"""HTTP (streamable-http) トランスポートでの起動。Cloudflare トンネル経由の公開用。

⚠️ このサーバーは（MT5_TRADE_ENABLED=true のとき）本番口座で実発注が可能です。
公開する場合はトークン認証が必須です。MT5_MCP_TOKEN 未設定では起動を拒否します
（MT5_MCP_ALLOW_NO_AUTH=true で明示的に無効化可能だが非推奨）。
"""

from __future__ import annotations

import hmac
import logging
import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import CONFIG

log = logging.getLogger("mt5_mcp.http")


def _env(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val is not None and val.strip() != "" else default


class BearerAuthMiddleware:
    """指定パス配下に Bearer トークン認証をかける ASGI ミドルウェア。

    /healthz など保護対象外のパスは素通しする。
    """

    def __init__(self, app, token: str, protect_prefix: str):
        self.app = app
        self.token = token
        self.protect_prefix = protect_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith(self.protect_prefix):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        expected = f"Bearer {self.token}"
        # タイミング攻撃に配慮して定数時間比較
        if not (auth and hmac.compare_digest(auth, expected)):
            response = JSONResponse(
                {"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Bearer token required or invalid."}},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def serve_http(mcp) -> None:
    """FastMCP を streamable-http で公開する。"""
    host = _env("MT5_MCP_HTTP_HOST", "127.0.0.1")
    port = int(_env("MT5_MCP_HTTP_PORT", "8790"))
    path = _env("MT5_MCP_HTTP_PATH", "/mcp")
    if not path.startswith("/"):
        path = "/" + path
    token = os.getenv("MT5_MCP_TOKEN", "").strip()
    allow_no_auth = _env("MT5_MCP_ALLOW_NO_AUTH", "false").lower() in ("1", "true", "yes", "on")

    # --- 安全チェック: 公開 + 発注有効 + 認証なし は危険 ---
    if not token and not allow_no_auth:
        raise SystemExit(
            "[中止] MT5_MCP_TOKEN が未設定です。HTTP 公開には Bearer トークンが必須です。\n"
            "  PowerShell 例:  $env:MT5_MCP_TOKEN = (\"<長いランダム文字列>\")\n"
            "  どうしても無認証で動かす場合のみ MT5_MCP_ALLOW_NO_AUTH=true を設定してください（非推奨）。"
        )
    if not token and CONFIG.trade_enabled:
        log.warning(
            "!!! 無認証 HTTP 公開かつ発注有効です。誰でも実発注できる状態です。直ちにトークンを設定してください。"
        )

    # FastMCP の設定を反映
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.streamable_http_path = path

    # DNS リバインディング保護（Host ヘッダ検証）の設定。
    # Cloudflare クイックトンネル経由では Host が毎回ランダムな *.trycloudflare.com になり、
    # allowed_hosts は完全一致のみ（サブドメインのワイルドカード非対応）のため検証を通せない。
    # 既定では保護を無効化（任意 Host 許可）し、必要なら MT5_MCP_ALLOWED_HOSTS でホスト固定する。
    allowed_hosts_env = _env("MT5_MCP_ALLOWED_HOSTS", "")
    if allowed_hosts_env.strip():
        hosts = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()]
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=hosts,
        )
        log.info("DNS rebinding protection ENABLED. allowed_hosts=%s", hosts)
    else:
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
        log.info("DNS rebinding protection disabled (any Host allowed; needed for tunnel).")

    # ヘルスチェック用ルート（認証不要）
    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request):  # noqa: ANN202
        return JSONResponse({"ok": True, "service": "mt5-mcp", "trade_enabled": CONFIG.trade_enabled})

    app = mcp.streamable_http_app()
    if token:
        app.add_middleware(BearerAuthMiddleware, token=token, protect_prefix=path)

    auth_state = "ENABLED (Bearer)" if token else "DISABLED (no auth)"
    log.info("MT5 MCP HTTP listening on http://%s:%s%s  auth=%s", host, port, path, auth_state)
    uvicorn.run(app, host=host, port=port, log_level="info")
