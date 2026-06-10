# MT5 MCP サーバー

MetaTrader 5 (MT5) と接続し、MCP クライアント（Claude Code / Claude Desktop 等）から
**マーケットデータ取得・テクニカル分析・フィボナッチ算出・売買発注**を行える MCP サーバー。

仕様は [`docs/specification.md`](docs/specification.md) を参照。

## 必要環境

- Windows 10/11（MT5 Python API は Windows 専用）
- Python 3.12+
- MT5 ターミナルがインストール・ログイン済みであること
- 発注を使う場合: MT5 で「ツール → オプション → エキスパートアドバイザー → アルゴリズム取引を許可」を有効化

## セットアップ

```powershell
cd C:\Users\jun\mt5-mcp
py -m pip install -r requirements.txt
copy .env.example .env   # 必要に応じて編集
```

MT5 が既にログイン済みなら `.env` の認証情報は省略可能です。

## 起動

```powershell
py -m mt5_mcp.server
```

## 動作確認（発注なし）

```powershell
py scripts\smoke_test.py USDJPY
```

全ツールが `[OK]` になれば正常です。

## MCP クライアントへの登録

`claude_desktop_config.json` などに以下を追加:

```json
{
  "mcpServers": {
    "mt5": {
      "command": "py",
      "args": ["-m", "mt5_mcp.server"],
      "cwd": "C:\\Users\\jun\\mt5-mcp"
    }
  }
}
```

> **注意（発注の有効化）**: 発注の有効/無効は `.env` の `MT5_TRADE_ENABLED` で決まります。
> ただし **OS/クライアントの環境変数が `.env` より優先**されます（`load_dotenv` の既定動作）。
> 上記 JSON の `env` に `"MT5_TRADE_ENABLED": "false"` を書くと、`.env` を `true` にしても**読み取り専用**になります。
> 発注を有効にしたい場合は `env` でこの変数を**指定しない**（=`.env` に従う）か、明示的に `"true"` を渡してください。
> サーバ起動ログに `発注ツールを登録しました (MT5_TRADE_ENABLED=true)` が出れば有効です。
> 実際の状態は `/healthz` の `trade_enabled` でも確認できます。

## リモート公開（Cloudflare トンネル）

MCP を HTTP で公開し、Cloudflare クイックトンネル経由で claude.ai / Cowork 等から接続できます。
サーバ起動とトンネルを **1つのスクリプト**で立ち上げます。`cloudflared` が PATH 上に必要です。

### claude.ai / Cowork に登録する場合（`-Cowork` モード）

claude.ai のカスタムコネクタは**静的 Bearer トークンに非対応**で、認証は OAuth のみです。
そのためトークン必須で起動すると、claude.ai が 401 を「OAuth が必要」と解釈して**OAuth 認証画面**を出します。
これを避けるため、**認証なし＋推測困難な秘密パス**で公開する `-Cowork` モードを使います:

```powershell
.\start-remote.ps1 -Cowork
```

- Bearer 認証を無効化（401 を出さない＝OAuth 要求が出ない）
- パス未指定なら `/mcp-<ランダム>` の秘密パスを自動生成
- 表示された **コネクタ URL（`https://<random>.trycloudflare.com/mcp-<random>`）をそのまま** claude.ai / Cowork のカスタムコネクタに登録（認証は「なし」のまま）

> ⚠️ **セキュリティ**: `-Cowork` モードはトークンが無いため、**URL（ホスト名＋秘密パス）を知る者は誰でも接続でき、`MT5_TRADE_ENABLED=true` なら実発注も可能**です。URL は絶対に共有しないでください。トンネルを再起動すると URL は変わります。閲覧のみで十分なら `.env` の `MT5_TRADE_ENABLED=false` を推奨します。

### Bearer トークンで保護する場合（既定モード／curl・Claude Code 等向け）

ヘッダーを送れるクライアント用。`Authorization: Bearer <token>` で認証します:

```powershell
$env:MT5_MCP_TOKEN = "<長いランダム文字列>"   # 省略時は自動生成
.\start-remote.ps1
```

### ローカル動作確認（トンネルなし・healthz/認証チェック）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test_http.ps1
```

## 提供ツール（全27ツール）

| カテゴリ | ツール |
|----------|--------|
| 接続/口座 | `mt5_health_check`, `mt5_account_info`, `mt5_terminal_info` |
| マーケット | `mt5_symbols_list`, `mt5_symbol_info`, `mt5_quote`, `mt5_market_depth` |
| ヒストリカル | `mt5_ohlcv`, `mt5_ticks` |
| 照会 | `mt5_positions`, `mt5_orders`, `mt5_history_deals`, `mt5_history_orders` |
| 指標 | `mt5_indicator`, `mt5_indicators_batch`（SMA/EMA/RSI/MACD/BB/ATR/Stochastic/ADX） |
| フィボナッチ | `mt5_swing_points`, `mt5_fib_retracement`, `mt5_fib_expansion` |
| 複合分析 | `mt5_market_snapshot`, `mt5_analyze`, `mt5_confluence` |
| 発注 ⚠️ | `mt5_order_send`, `mt5_position_close`, `mt5_position_modify`, `mt5_order_modify`, `mt5_order_cancel`, `mt5_close_all` |

発注系は `MT5_TRADE_ENABLED=true` のときのみ登録されます。

## 安全機構（発注ガード）

1. **マスタースイッチ**: `MT5_TRADE_ENABLED=false`（既定）では発注ツール自体を登録しない
2. **二段階確認**: `confirm=true` の無い発注は `order_check` によるドライラン（プレビュー）に変換
3. **ロット上限**: `MT5_MAX_LOT` 超過を拒否
4. **シンボルホワイトリスト**: `MT5_ALLOWED_SYMBOLS`
5. **スリッページ上限**: `MT5_MAX_SLIPPAGE` を強制適用
6. **監査ログ**: 全発注操作を `~/.mt5_mcp/trade_audit.log` に記録

> ⚠️ **発注機能は必ずデモ口座で十分に検証してから本番口座で使用してください。**

## ライセンス / 注意

本ソフトウェアは無保証です。自動売買・発注に伴う損失について作者は責任を負いません。
```
