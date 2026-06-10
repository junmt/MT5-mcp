# MT5 MCP サーバー 仕様書

最終更新: 2026-06-10
バージョン: 0.1 (ドラフト)

---

## 1. 概要

MetaTrader 5 (MT5) と接続し、Claude などの MCP クライアントから**マーケットデータの取得・チャート分析・売買発注**を行えるようにする MCP (Model Context Protocol) サーバー。

公式 `MetaTrader5` Python パッケージを介して、ローカル PC 上で稼働している MT5 ターミナルを操作する。

### 1.1 目的

- AI アシスタントが MT5 の口座・相場情報を直接読み取り、テクニカル分析を行える。
- 分析結果に基づいて、新規注文・決済・ポジション変更などの売買操作を実行できる。
- 実発注を伴うため、誤発注を防ぐ**安全機構**を標準で備える。

### 1.2 スコープ

| 区分 | 内容 | 本仕様での扱い |
|------|------|----------------|
| 閲覧 | 価格・板・口座・ポジション・履歴・テクニカル指標 | ✅ フル対応 |
| 発注 | 成行/指値/逆指値、決済、SL/TP 変更、注文取消 | ✅ フル対応 |
| 利用形態 | 個人のローカル利用（同一 PC 上の MT5） | ✅ |
| トランスポート | stdio | ✅ |
| リモート/マルチユーザー | HTTP/SSE・認証 | ❌ 対象外（将来拡張） |

---

## 2. 動作環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11（MT5 ターミナルが Windows 専用のため） |
| Python | 3.12 系（検証環境: 3.12.10） |
| MT5 ターミナル | インストール済み・ログイン済みであること |
| 主要パッケージ | `MetaTrader5`, `mcp` (FastMCP), `pandas`（任意） |
| 文字コード | UTF-8 |

> MT5 ターミナルは「ツール → オプション → エキスパートアドバイザー → アルゴリズム取引を許可」を有効にする必要がある（発注機能を使う場合）。

---

## 3. アーキテクチャ

```
┌──────────────┐   MCP(stdio)   ┌─────────────────┐   IPC    ┌──────────────┐
│ MCP クライアント │ ◀───────────▶ │  MT5 MCP サーバー   │ ◀─────▶ │ MT5 ターミナル  │
│ (Claude Code 等) │   JSON-RPC    │  (Python/FastMCP) │  pymt5   │  (Windows)    │
└──────────────┘                └─────────────────┘          └──────┬───────┘
                                                                     │
                                                              ブローカーサーバー
```

### 3.1 レイヤー構成

```
mt5_mcp/
├── server.py            # FastMCP エントリポイント / ツール登録
├── connection.py        # MT5 初期化・ログイン・再接続・ライフサイクル
├── config.py            # 設定読み込み（環境変数 / .env）
├── safety.py            # 発注ガード（確認フラグ・上限・許可シンボル）
├── tools/
│   ├── market.py        # 価格・板・シンボル情報
│   ├── history.py       # OHLCV・ティック履歴
│   ├── indicators.py    # テクニカル指標計算
│   ├── fibonacci.py     # フィボナッチ算出・スイング検出
│   ├── account.py       # 口座・ポジション・注文状況
│   ├── trade.py         # 発注・決済・変更・取消
│   └── analysis.py      # 複合分析（高水準ツール）
└── utils/
    ├── mapping.py       # タイムフレーム/注文種別の文字列⇔定数変換
    └── format.py        # 数値整形・JSON シリアライズ
```

### 3.2 ライフサイクル

1. サーバー起動時に `MetaTrader5.initialize()` を実行（必要に応じて `login()`）。
2. 接続失敗時はリトライ（指数バックオフ、最大 N 回）。
3. 各ツール呼び出し前に接続状態を確認し、切断時は自動再接続。
4. サーバー終了時に `MetaTrader5.shutdown()`。

---

## 4. 設定

`.env` または環境変数で指定。MT5 が既にログイン済みなら認証情報は省略可能。

| 変数 | 必須 | 既定 | 説明 |
|------|------|------|------|
| `MT5_PATH` | 任意 | 自動検出 | terminal64.exe のパス |
| `MT5_LOGIN` | 任意 | - | 口座番号 |
| `MT5_PASSWORD` | 任意 | - | パスワード |
| `MT5_SERVER` | 任意 | - | ブローカーサーバー名 |
| `MT5_TIMEOUT` | 任意 | 60000 | 接続タイムアウト(ms) |
| `MT5_TRADE_ENABLED` | 任意 | `false` | 発注ツールの有効化フラグ（**安全のため既定無効**） |
| `MT5_TRADE_CONFIRM` | 任意 | `true` | 発注時の二段階確認を要求 |
| `MT5_ALLOWED_SYMBOLS` | 任意 | `*` | 発注を許可するシンボルのホワイトリスト（カンマ区切り） |
| `MT5_MAX_LOT` | 任意 | `1.0` | 1 注文あたりの最大ロット |
| `MT5_MAX_SLIPPAGE` | 任意 | `20` | 許容スリッページ(points) |
| `MT5_MAGIC` | 任意 | `20260610` | 注文のマジックナンバー |

---

## 5. 提供ツール（MCP Tools）

戻り値はすべて JSON。エラーは `{ "ok": false, "error": { "code", "message" } }` 形式で統一。

### 5.1 接続・口座系

| ツール名 | 概要 | 主な引数 | 戻り値 |
|----------|------|----------|--------|
| `mt5_health_check` | 接続状態・ターミナル情報 | - | 接続状態, version, ping |
| `mt5_account_info` | 口座情報 | - | balance, equity, margin, free_margin, leverage, currency |
| `mt5_terminal_info` | ターミナル設定 | - | trade_allowed, connected, path |

### 5.2 マーケットデータ系

| ツール名 | 概要 | 主な引数 | 戻り値 |
|----------|------|----------|--------|
| `mt5_symbols_list` | 利用可能シンボル一覧 | `group?`（フィルタ） | symbol[] |
| `mt5_symbol_info` | シンボル詳細 | `symbol` | spread, digits, point, contract_size, min/max/step lot, trade_mode |
| `mt5_quote` | 現在気配 | `symbol` | bid, ask, last, spread, time |
| `mt5_market_depth` | 板情報(DOM) | `symbol` | bids[], asks[] |

### 5.3 ヒストリカルデータ系

| ツール名 | 概要 | 主な引数 | 戻り値 |
|----------|------|----------|--------|
| `mt5_ohlcv` | ローソク足取得 | `symbol`, `timeframe`, `count?`, `from?`, `to?` | bars[] (time,o,h,l,c,volume), summary |
| `mt5_ticks` | ティック履歴 | `symbol`, `from`, `count?` | ticks[] |

- `timeframe`: `M1,M5,M15,M30,H1,H4,D1,W1,MN1` などの文字列で受け取り、内部で `mt5.TIMEFRAME_*` に変換。
- `count` 既定 100、上限 5000（過大取得防止）。
- `mt5_ohlcv` は既定で `summary=true`（OHLC 範囲・件数・最新足のみ）。全足が必要な場合のみ `full=true`。

### 5.4 テクニカル指標系

| ツール名 | 概要 | 主な引数 |
|----------|------|----------|
| `mt5_indicator` | 単一指標を計算 | `symbol`, `timeframe`, `name`, `params?` |
| `mt5_indicators_batch` | 複数指標を一括計算 | `symbol`, `timeframe`, `indicators[]` |

サポート指標（初期実装）: `SMA, EMA, RSI, MACD, BollingerBands, ATR, Stochastic, ADX`。
MT5 のコピー系 API でバーを取得し、Python 側で計算（`pandas`/自前実装）。MT5 内蔵インジケータハンドルは将来拡張。

### 5.4.1 フィボナッチ系

スイング（高値・安値）を基準に価格レベルを算出する。手動指定と自動検出の両方に対応する。

| ツール名 | 概要 | 主な引数 |
|----------|------|----------|
| `mt5_fib_retracement` | フィボナッチ・リトレースメント水準を算出 | `symbol`, `timeframe`, （`high`,`low` または `auto=true`）, `direction?`, `levels?` |
| `mt5_fib_expansion` | フィボナッチ・エクスパンション（エクステンション）水準を算出 | `symbol`, `timeframe`, （`p1`,`p2`,`p3` または `auto=true`）, `levels?` |
| `mt5_swing_points` | スイング高値・安値（ZigZag 相当）を検出 | `symbol`, `timeframe`, `count?`, `depth?` |

#### 引数と挙動

- **リトレースメント**
  - 手動: `high`（基点高値）, `low`（基点安値）, `direction`（`up`=安値→高値の上昇波 / `down`=高値→安値の下落波）を指定。
  - 自動: `auto=true` の場合、`mt5_swing_points` で直近の有効なスイング 2 点を検出して基点とする。
  - `levels` 既定: `[0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]`（任意で上書き可、`1.272`,`1.618` 等の延長水準も指定可）。
- **エクスパンション**（3 点法）
  - 手動: `p1`(始点), `p2`(波の終点), `p3`(押し/戻りの起点) の 3 価格を指定。
  - 自動: `auto=true` で直近のスイング 3 点（A-B-C）を検出。
  - `levels` 既定: `[0, 0.382, 0.618, 1.0, 1.382, 1.618, 2.0, 2.618]`。
- 戻り値: 各 `level` に対する `price`（`digits` で丸め）、基点 (`anchors`)、現在価格との位置関係（どの水準帯にいるか）、`direction` を含む。
- `auto=true` 利用時は、検出に使ったスイング点・確度を併せて返し、誤検出時に手動指定へ切替できるようにする。

#### スイング検出

`mt5_swing_points` は ZigZag 系アルゴリズム（`depth`/振幅閾値）で極大・極小を抽出する。フィボナッチツールの `auto` 検出の基盤となる。

### 5.5 ポジション・注文照会系

| ツール名 | 概要 | 主な引数 |
|----------|------|----------|
| `mt5_positions` | オープンポジション一覧 | `symbol?` |
| `mt5_orders` | 未約定（待機）注文一覧 | `symbol?` |
| `mt5_history_deals` | 約定履歴 | `from`, `to`, `symbol?` |
| `mt5_history_orders` | 注文履歴 | `from`, `to`, `symbol?` |

### 5.6 発注・取引系（**要 `MT5_TRADE_ENABLED=true`**）

| ツール名 | 概要 | 主な引数 |
|----------|------|----------|
| `mt5_order_send` | 成行/指値/逆指値の新規注文 | `symbol`, `side`(buy/sell), `type`(market/limit/stop), `volume`, `price?`, `sl?`, `tp?`, `comment?`, `confirm` |
| `mt5_position_close` | ポジション決済（全部/一部） | `ticket`, `volume?`, `confirm` |
| `mt5_position_modify` | SL/TP 変更 | `ticket`, `sl?`, `tp?`, `confirm` |
| `mt5_order_modify` | 待機注文の価格/SL/TP 変更 | `ticket`, `price?`, `sl?`, `tp?`, `confirm` |
| `mt5_order_cancel` | 待機注文の取消 | `ticket`, `confirm` |
| `mt5_close_all` | 条件一致ポジションの一括決済 | `symbol?`, `confirm` |

#### 発注フロー（二段階確認）
1. `confirm` 省略/`false` の場合 → **プレビュー（ドライラン）** を返す。
   - `mt5.order_check()` で証拠金・約定可否・想定コストを検証した結果を返却。
2. クライアント（AI/ユーザー）が内容を確認し `confirm=true` で再呼び出し → 実発注。
3. 実発注は `mt5.order_send()` を実行し、`retcode` と約定情報を返す。

### 5.7 複合分析系（高水準）

| ツール名 | 概要 |
|----------|------|
| `mt5_market_snapshot` | 指定シンボルの気配・スプレッド・主要指標・直近トレンドをまとめて返す |
| `mt5_analyze` | 複数タイムフレームのトレンド/モメンタムを要約し、所見テキストを生成 |
| `mt5_confluence` | 主要フィボ水準・直近スイング・指標を重ね合わせ、注目価格帯（コンフルエンス）を抽出 |

---

## 6. 安全設計（発注ガード）

実発注を伴うため、`safety.py` で以下を**多層防御**として実装する。

1. **マスタースイッチ**: `MT5_TRADE_ENABLED=false`（既定）では発注系ツール自体を登録しない／拒否。
2. **二段階確認**: `confirm=true` が無い発注はすべてドライラン（`order_check`）に変換。
3. **ロット上限**: `MT5_MAX_LOT` を超える `volume` を拒否。
4. **シンボルホワイトリスト**: `MT5_ALLOWED_SYMBOLS` に無いシンボルは拒否。
5. **スリッページ上限**: `MT5_MAX_SLIPPAGE` を deviation に強制適用。
6. **アルゴ取引チェック**: `terminal_info.trade_allowed` が false の場合は明示エラー。
7. **監査ログ**: 全発注操作（ドライラン含む）をローカルログファイルに記録（時刻・ツール・引数・結果 retcode）。
8. **マジックナンバー**: 本サーバー発注を識別できるよう `MT5_MAGIC` を付与。

---

## 7. エラーハンドリング

| 区分 | 例 | 対応 |
|------|----|------|
| 接続エラー | initialize 失敗 / 切断 | 再接続リトライ → 失敗時 `CONNECTION_ERROR` |
| 入力エラー | 未知 timeframe / 不正シンボル | `INVALID_ARGUMENT` |
| 安全制約違反 | ロット超過 / 非許可シンボル / trade 無効 | `SAFETY_BLOCKED` |
| 取引エラー | retcode != DONE | `TRADE_ERROR`（retcode と意味を付与） |
| 内部エラー | 想定外例外 | `INTERNAL_ERROR`（スタックはログのみ） |

MT5 の `last_error()` を取得して `code`/`message` に反映する。

---

## 8. データ形式の取り決め

- 時刻: ISO 8601（UTC, 末尾 `Z`）。MT5 のサーバー時刻はブローカー TZ のため、UTC 換算して返す。換算前後双方を返す場合は `time_server` / `time_utc` を併記。
- 価格・数量: `digits` に基づき丸めた数値。文字列ではなく数値型。
- ロット: float（例 0.01 単位）。
- レスポンス上限: 大きな配列は既定で要約。`full=true` 明示時のみ全件返却し、上限 5000 件。

---

## 9. 実装フェーズ計画

| フェーズ | 内容 | 完了条件 |
|----------|------|----------|
| P0 | プロジェクト雛形・接続管理・`mt5_health_check` | 接続できヘルスチェックが通る |
| P1 | マーケット/ヒストリカル/口座照会の閲覧系 | 価格・OHLCV・ポジション取得 |
| P2 | テクニカル指標・フィボナッチ・複合分析 | RSI/MACD・フィボ水準・スイング検出が計算できる |
| P3 | 発注系（ドライラン → 実発注）+ 安全機構 | デモ口座で発注/決済が通る |
| P4 | 監査ログ・エラー整備・ドキュメント | README/利用手順完成 |

---

## 10. テスト方針

- **接続テスト**: MT5 起動/未起動の双方を検証。
- **閲覧系**: 既知シンボル（例 `EURUSD`）でスキーマ検証。
- **発注系**: **必ずデモ口座**で実施。`order_check` ドライランの単体テスト、実発注は手動承認下で実施。
- **安全機構**: ロット超過・非許可シンボル・trade 無効時に確実にブロックされること。

---

## 11. 既知の制約・将来拡張

- MT5 Python API は Windows のみ。リモート利用時はブリッジ（HTTP/SSE）が別途必要 → 将来拡張。
- 1 プロセスから複数 MT5 ターミナルへの同時接続は不可（公式制約）。
- 内蔵インジケータの一部は Python から直接呼べないため自前計算で代替。
- 将来: 経済指標カレンダー連携、複数口座対応、バックテスト連携、TradingView MCP との統合分析。
```
