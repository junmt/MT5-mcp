"""テクニカル指標系ツール。仕様書 §5.4。

MT5 のバーを取得し、pandas で計算する（内蔵ハンドル非依存）。
"""

from __future__ import annotations

import pandas as pd

from ..connection import last_error, mt
from ..utils.format import epoch_to_utc_iso, err, ok
from ..utils.mapping import parse_timeframe

_MAX_BARS = 5000


def _fetch_df(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    tf = parse_timeframe(timeframe)
    count = max(2, min(int(count), _MAX_BARS))
    m = mt()
    rates = m.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        code, desc = last_error()
        raise RuntimeError(f"バー取得失敗: {desc} (code={code})")
    df = pd.DataFrame(rates)
    return df


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _last(series: pd.Series) -> float | None:
    val = series.dropna()
    if val.empty:
        return None
    return float(val.iloc[-1])


def _compute(df: pd.DataFrame, name: str, params: dict) -> dict:
    name = name.strip().lower()
    close = df["close"]

    if name == "sma":
        n = int(params.get("period", 20))
        return {"value": _last(_sma(close, n)), "period": n}

    if name == "ema":
        n = int(params.get("period", 20))
        return {"value": _last(_ema(close, n)), "period": n}

    if name == "rsi":
        n = int(params.get("period", 14))
        return {"value": _last(_rsi(close, n)), "period": n}

    if name == "macd":
        fast = int(params.get("fast", 12))
        slow = int(params.get("slow", 26))
        signal = int(params.get("signal", 9))
        macd_line = _ema(close, fast) - _ema(close, slow)
        signal_line = _ema(macd_line, signal)
        hist = macd_line - signal_line
        return {
            "macd": _last(macd_line),
            "signal": _last(signal_line),
            "histogram": _last(hist),
            "fast": fast,
            "slow": slow,
            "signal_period": signal,
        }

    if name in ("bollinger", "bollingerbands", "bb"):
        n = int(params.get("period", 20))
        k = float(params.get("stddev", 2.0))
        mid = _sma(close, n)
        std = close.rolling(n).std()
        return {
            "middle": _last(mid),
            "upper": _last(mid + k * std),
            "lower": _last(mid - k * std),
            "period": n,
            "stddev": k,
        }

    if name == "atr":
        n = int(params.get("period", 14))
        return {"value": _last(_atr(df, n)), "period": n}

    if name in ("stoch", "stochastic"):
        k_period = int(params.get("k", 14))
        d_period = int(params.get("d", 3))
        low_min = df["low"].rolling(k_period).min()
        high_max = df["high"].rolling(k_period).max()
        k_line = 100 * (close - low_min) / (high_max - low_min)
        d_line = k_line.rolling(d_period).mean()
        return {"k": _last(k_line), "d": _last(d_line), "k_period": k_period, "d_period": d_period}

    if name == "adx":
        n = int(params.get("period", 14))
        high, low = df["high"], df["low"]
        up = high.diff()
        down = -low.diff()
        plus_dm = ((up > down) & (up > 0)) * up
        minus_dm = ((down > up) & (down > 0)) * down
        atr = _atr(df, n)
        plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.ewm(alpha=1 / n, adjust=False).mean()
        return {"adx": _last(adx), "plus_di": _last(plus_di), "minus_di": _last(minus_di), "period": n}

    raise ValueError(f"未対応の指標: {name}")


_SUPPORTED = ["sma", "ema", "rsi", "macd", "bollinger", "atr", "stochastic", "adx"]


def register(mcp) -> None:
    @mcp.tool()
    def mt5_indicator(
        symbol: str,
        timeframe: str,
        name: str,
        params: dict | None = None,
        count: int = 200,
    ) -> dict:
        """単一のテクニカル指標を計算する。

        name: sma, ema, rsi, macd, bollinger, atr, stochastic, adx
        params: 指標ごとのパラメータ（例 {"period": 14}, MACD は {"fast":12,"slow":26,"signal":9}）
        """
        try:
            df = _fetch_df(symbol, timeframe, count)
            result = _compute(df, name, params or {})
            return ok(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.upper(),
                    "name": name.lower(),
                    "at": epoch_to_utc_iso(df["time"].iloc[-1]),
                    "result": result,
                }
            )
        except ValueError as exc:
            return err("INVALID_ARGUMENT", str(exc))
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

    @mcp.tool()
    def mt5_indicators_batch(
        symbol: str,
        timeframe: str,
        indicators: list[dict],
        count: int = 200,
    ) -> dict:
        """複数指標を一括計算する。

        indicators: [{"name":"rsi","params":{"period":14}}, {"name":"macd"}, ...]
        """
        try:
            df = _fetch_df(symbol, timeframe, count)
        except Exception as exc:  # noqa: BLE001
            return err("INTERNAL_ERROR", str(exc))

        out = []
        for spec in indicators:
            nm = spec.get("name", "")
            try:
                res = _compute(df, nm, spec.get("params") or {})
                out.append({"name": nm.lower(), "result": res})
            except Exception as exc:  # noqa: BLE001
                out.append({"name": nm, "error": str(exc)})
        return ok(
            {
                "symbol": symbol,
                "timeframe": timeframe.upper(),
                "at": epoch_to_utc_iso(df["time"].iloc[-1]),
                "indicators": out,
                "supported": _SUPPORTED,
            }
        )
