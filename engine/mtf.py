import pandas as pd

from indicators.technicals import add_indicators


def _directional_check(buy_condition, sell_condition):
    if buy_condition:
        return 1
    if sell_condition:
        return -1
    return 0


def summarize_timeframe(df: pd.DataFrame):
    """
    Return a directional score for one timeframe.

    Positive values favour BUY, negative values favour SELL.
    The public `score` remains 0-100 for compatibility:
        50 = neutral
        >50 = bullish
        <50 = bearish
    """

    if df is None or df.empty or len(df) < 30:
        return {
            "signal": "NO DATA",
            "score": 50,
            "direction_score": 0,
            "price": None,
            "rsi": None,
            "rvol": None,
        }

    df = add_indicators(df)
    last = df.iloc[-1]

    values = [
        _directional_check(
            last["close"] > last["ema20"],
            last["close"] < last["ema20"],
        ),
        _directional_check(
            last["ema20"] > last["ema50"],
            last["ema20"] < last["ema50"],
        ),
        _directional_check(
            last["ema50"] > last["ema200"],
            last["ema50"] < last["ema200"],
        ),
        _directional_check(
            last["close"] > last["vwap"],
            last["close"] < last["vwap"],
        ),
        _directional_check(
            last["rsi"] >= 50,
            last["rsi"] < 50,
        ),
        _directional_check(
            last["supertrend"] == 1,
            last["supertrend"] == -1,
        ),
        _directional_check(
            last["macd"] > last["macd_signal"],
            last["macd"] < last["macd_signal"],
        ),
    ]

    direction_score = sum(values) / len(values) * 100
    score = int(round(50 + direction_score / 2))

    if score >= 65:
        signal = "BUY"
    elif score <= 35:
        signal = "SELL"
    else:
        signal = "WATCH"

    return {
        "signal": signal,
        "score": score,
        "direction_score": round(direction_score, 1),
        "price": float(last["close"]),
        "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else None,
        "rvol": float(last["rvol"]) if pd.notna(last["rvol"]) else None,
        "ema20": float(last["ema20"]),
        "ema50": float(last["ema50"]),
        "ema200": float(last["ema200"]),
        "vwap": float(last["vwap"]),
        "atr": float(last["atr"]),
        "supertrend": int(last["supertrend"]),
        "macd_bull": bool(last["macd"] > last["macd_signal"]),
    }
