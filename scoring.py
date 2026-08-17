def score_technical(df):
    last = df.iloc[-1]

    bull = 0
    bear = 0
    reasons = []
    risks = []

    if last["close"] > last["ema20"]:
        bull += 10
        reasons.append("Price above EMA20")
    else:
        bear += 10
        risks.append("Price below EMA20")

    if last["ema20"] > last["ema50"]:
        bull += 10
        reasons.append("EMA20 > EMA50")
    else:
        bear += 10
        risks.append("EMA20 below EMA50")

    if last["ema50"] > last["ema200"]:
        bull += 8
        reasons.append("EMA50 > EMA200")
    else:
        bear += 8
        risks.append("EMA50 below EMA200")

    if last["close"] > last["vwap"]:
        bull += 8
        reasons.append("Price above VWAP")
    else:
        bear += 8
        risks.append("Price below VWAP")

    if last["rsi"] >= 55:
        bull += 6
        reasons.append(f"RSI bullish ({last['rsi']:.1f})")
    elif last["rsi"] <= 45:
        bear += 6
        risks.append(f"RSI bearish ({last['rsi']:.1f})")

    if last["rvol"] >= 2:
        bull += 8
        bear += 8
        reasons.append(f"Strong volume expansion ({last['rvol']:.2f}x)")
    elif last["rvol"] >= 1.5:
        bull += 5
        bear += 5
        reasons.append(f"Volume expansion ({last['rvol']:.2f}x)")
    else:
        risks.append("Volume confirmation is weak")

    if last["supertrend"] == 1:
        bull += 5
        reasons.append("SuperTrend bullish")
    else:
        bear += 5
        risks.append("SuperTrend bearish")

    if last["macd"] > last["macd_signal"]:
        bull += 5
        reasons.append("MACD bullish")
    else:
        bear += 5
        risks.append("MACD bearish")

    total_directional = bull + bear
    if total_directional == 0:
        return {"score": 50, "signal": "WAIT", "reasons": reasons, "risks": risks}

    # Directional score normalized to 0-100.
    score = round(100 * bull / total_directional)

    if score >= 75:
        signal = "BUY"
    elif score <= 25:
        signal = "SELL"
    else:
        signal = "WATCH"

    return {
        "score": score,
        "signal": signal,
        "reasons": reasons,
        "risks": risks,
    }
