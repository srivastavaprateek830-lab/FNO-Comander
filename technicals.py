import numpy as np
import pandas as pd


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()

    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    return (tp * vol).cumsum() / vol.cumsum()


def supertrend_direction(df, period=10, multiplier=3.0):
    # Direction-only implementation for the first MVP.
    a = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper = hl2 + multiplier * a
    lower = hl2 - multiplier * a

    direction = [1]
    for i in range(1, len(df)):
        prev_dir = direction[-1]
        close = df["close"].iloc[i]

        if close > upper.iloc[i - 1]:
            direction.append(1)
        elif close < lower.iloc[i - 1]:
            direction.append(-1)
        else:
            direction.append(prev_dir)

    return pd.Series(direction, index=df.index)


def add_indicators(df):
    out = df.copy()

    out["ema20"] = ema(out["close"], 20)
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)

    out["rsi"] = rsi(out["close"], 14)
    out["atr"] = atr(out, 14)
    out["vwap"] = vwap(out)

    out["volume_ma20"] = out["volume"].rolling(20).mean()
    out["rvol"] = out["volume"] / out["volume_ma20"].replace(0, np.nan)

    out["supertrend"] = supertrend_direction(out)

    # Simple MACD confirmation.
    out["macd"] = ema(out["close"], 12) - ema(out["close"], 26)
    out["macd_signal"] = ema(out["macd"], 9)

    return out
