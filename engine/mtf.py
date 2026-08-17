import pandas as pd

from indicators.technicals import add_indicators


def summarize_timeframe(df: pd.DataFrame):
    if df is None or df.empty:
        return {
            "signal": "NO DATA",
            "score": 50,
            "price": None,
            "rsi": None,
            "rvol": None,
        }

    df = add_indicators(df)
    last = df.iloc[-1]

    checks = [
        bool(last["close"] > last["ema20"]),
        bool(last["ema20"] > last["ema50"]),
        bool(last["ema50"] > last["ema200"]),
        bool(last["close"] > last["vwap"]),
        bool(last["rsi"] >= 50),
        bool(last["supertrend"] == 1),
        bool(last["macd"] > last["macd_signal"]),
    ]
    score = round(sum(checks) / len(checks) * 100)

    if score >= 70:
        signal = "BUY"
    elif score <= 30:
        signal = "SELL"
    else:
        signal = "WATCH"

    return {
        "signal": signal,
        "score": score,
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
