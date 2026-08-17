import numpy as np
import pandas as pd


def _clean_ohlcv(df):
    out = df.copy()

    for col in ["open", "high", "low", "close", "volume"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["high", "low", "close"]).copy()
    out["volume"] = out["volume"].fillna(0)

    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
        out = out.sort_values("timestamp").reset_index(drop=True)

    return out


def ema(series, period):
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))

    # Explicit edge handling:
    # continuous gains should read as 100, continuous losses as 0.
    result = result.where(avg_loss != 0, 100)
    result = result.where(avg_gain != 0, 0)

    return result


def atr(df, period=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()

    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)

    return tr.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def vwap(df):
    """
    Intraday/session VWAP.

    The previous implementation accumulated VWAP across the entire
    60-day dataframe. That is not a proper intraday VWAP. This version
    resets cumulative price*volume and volume at each trading session.
    """

    tp = (df["high"] + df["low"] + df["close"]) / 3
    volume = df["volume"].fillna(0)

    if "timestamp" in df.columns and pd.api.types.is_datetime64_any_dtype(
        df["timestamp"]
    ):
        session = df["timestamp"].dt.date
        pv = (tp * volume).groupby(session).cumsum()
        vv = volume.groupby(session).cumsum()
    else:
        # Fallback if timestamps are unavailable.
        pv = (tp * volume).cumsum()
        vv = volume.cumsum()

    return pv / vv.replace(0, np.nan)


def supertrend_direction(df, period=10, multiplier=3.0):
    """
    Direction-only SuperTrend.

    Returns:
        +1 bullish
        -1 bearish
    """

    a = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2

    basic_upper = hl2 + multiplier * a
    basic_lower = hl2 - multiplier * a

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()

    direction = pd.Series(index=df.index, dtype="int64")

    if len(df) == 0:
        return direction

    direction.iloc[0] = 1

    for i in range(1, len(df)):
        prev_close = df["close"].iloc[i - 1]

        if (
            basic_upper.iloc[i] < final_upper.iloc[i - 1]
            or prev_close > final_upper.iloc[i - 1]
        ):
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        if (
            basic_lower.iloc[i] > final_lower.iloc[i - 1]
            or prev_close < final_lower.iloc[i - 1]
        ):
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        prev_direction = direction.iloc[i - 1]
        close = df["close"].iloc[i]

        if prev_direction == -1 and close > final_upper.iloc[i]:
            direction.iloc[i] = 1
        elif prev_direction == 1 and close < final_lower.iloc[i]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = prev_direction

    return direction


def add_indicators(df):
    out = _clean_ohlcv(df)

    out["ema20"] = ema(out["close"], 20)
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)

    out["rsi"] = rsi(out["close"], 14)
    out["atr"] = atr(out, 14)
    out["vwap"] = vwap(out)

    # ------------------------------------------------------------------
    # Relative Volume (RVOL)
    # ------------------------------------------------------------------
    # For intraday candles, comparing a 15-minute bar with the previous
    # 20 arbitrary candles is misleading because different time-of-day
    # bars naturally have different volumes.  Compare each bar with the
    # same time-slot on prior sessions instead.
    if "timestamp" in out.columns and pd.api.types.is_datetime64_any_dtype(
        out["timestamp"]
    ):
        out["_session"] = out["timestamp"].dt.date
        out["_slot"] = out["timestamp"].dt.strftime("%H:%M")

        same_slot_avg = (
            out.groupby("_slot")["volume"]
            .transform(
                lambda s: s.shift(1).rolling(20, min_periods=5).mean()
            )
        )

        # Warm-up fallback: rolling average of the preceding 20 bars.
        fallback_avg = out["volume"].shift(1).rolling(
            20, min_periods=10
        ).mean()

        reference_volume = same_slot_avg.fillna(fallback_avg)

        out["rvol"] = (
            out["volume"]
            / reference_volume.replace(0, np.nan)
        )

        out.drop(columns=["_session", "_slot"], inplace=True, errors="ignore")
    else:
        reference_volume = out["volume"].shift(1).rolling(
            20, min_periods=10
        ).mean()
        out["rvol"] = (
            out["volume"]
            / reference_volume.replace(0, np.nan)
        )

    out["supertrend"] = supertrend_direction(out)

    # MACD 12/26/9
    out["macd"] = (
        ema(out["close"], 12)
        - ema(out["close"], 26)
    )
    out["macd_signal"] = ema(out["macd"], 9)
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    return out
