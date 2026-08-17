"""
FNO COMMANDER - Technical Stage-2 Scoring

This is the fast 15-minute score used before the slower MTF/OI
enrichment. It is intentionally deterministic and directional.
"""

import math


def _valid(value):
    try:
        return value is not None and not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def score_technical(df):
    if df is None or df.empty:
        return {
            "score": 50,
            "signal": "WATCH",
            "reasons": ["No technical data"],
            "risks": ["No technical data"],
        }

    last = df.iloc[-1]

    bull = 0
    bear = 0
    reasons = []
    risks = []

    def add_direction(condition, weight, bull_reason, bear_reason):
        nonlocal bull, bear
        if condition is True:
            bull += weight
            reasons.append(bull_reason)
        elif condition is False:
            bear += weight
            risks.append(bear_reason)

    # EMA structure — 30
    if all(_valid(last.get(c)) for c in ["close", "ema20", "ema50", "ema200"]):
        add_direction(
            last["close"] > last["ema20"] > last["ema50"] > last["ema200"],
            30,
            "Price > EMA20 > EMA50 > EMA200",
            "Bearish EMA stack",
        )
    else:
        risks.append("EMA data incomplete")

    # VWAP — 15
    if _valid(last.get("close")) and _valid(last.get("vwap")):
        add_direction(
            last["close"] > last["vwap"],
            15,
            "Price above session VWAP",
            "Price below session VWAP",
        )

    # RSI — 10
    if _valid(last.get("rsi")):
        rsi = float(last["rsi"])
        if rsi >= 55:
            bull += 10
            reasons.append(f"RSI bullish ({rsi:.1f})")
        elif rsi <= 45:
            bear += 10
            risks.append(f"RSI bearish ({rsi:.1f})")
        else:
            risks.append(f"RSI neutral ({rsi:.1f})")

    # RVOL — 15
    if _valid(last.get("rvol")):
        rvol = float(last["rvol"])
        if rvol >= 2.0:
            bull += 15
            bear += 15
            reasons.append(f"Strong volume expansion ({rvol:.2f}x)")
        elif rvol >= 1.2:
            bull += 10
            bear += 10
            reasons.append(f"Good participation ({rvol:.2f}x)")
        elif rvol >= 0.8:
            bull += 5
            bear += 5
            risks.append(f"Volume below ideal ({rvol:.2f}x)")
        else:
            risks.append(f"Weak RVOL ({rvol:.2f}x)")

    # SuperTrend — 10
    if _valid(last.get("supertrend")):
        if int(last["supertrend"]) == 1:
            bull += 10
            reasons.append("SuperTrend bullish")
        else:
            bear += 10
            risks.append("SuperTrend bearish")

    # MACD — 10
    if _valid(last.get("macd")) and _valid(last.get("macd_signal")):
        if last["macd"] > last["macd_signal"]:
            bull += 10
            reasons.append("MACD bullish")
        else:
            bear += 10
            risks.append("MACD bearish")

    total = bull + bear

    if total == 0:
        return {
            "score": 50,
            "signal": "WATCH",
            "reasons": reasons,
            "risks": risks,
        }

    score = round(100 * bull / total)

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
