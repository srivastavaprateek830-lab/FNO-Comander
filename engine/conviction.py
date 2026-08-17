"""
FNO COMMANDER - V2B Conviction Engine

Combines the existing scanner output with additional confirmation
factors without replacing the existing Dhan/data pipeline.

Score philosophy:
- Positive confirmations add points.
- Neutral conditions add little/no points.
- Contradictory conditions reduce conviction.
- Critical failures can trigger a veto.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FactorResult:
    name: str
    score: float
    maximum: float
    status: str
    reason: str


@dataclass
class ConvictionResult:
    symbol: str
    direction: str
    score: float
    status: str
    factors: List[FactorResult] = field(default_factory=list)
    vetoes: List[str] = field(default_factory=list)
    positives: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _factor(name, score, maximum, status, reason):
    return FactorResult(
        name=name,
        score=float(score),
        maximum=float(maximum),
        status=status,
        reason=reason,
    )


def _bool_factor(name, condition, maximum, positive_reason, negative_reason):
    if condition:
        return _factor(
            name,
            maximum,
            maximum,
            "PASS",
            positive_reason,
        )

    return _factor(
        name,
        0,
        maximum,
        "FAIL",
        negative_reason,
    )


def calculate_conviction(
    row: Dict,
    mtf_score: Optional[float] = None,
    market_bias: Optional[str] = None,
    oi_bias: Optional[str] = None,
    option_bias: Optional[str] = None,
):
    """
    Calculate an independent V2B conviction score.

    The function is deliberately tolerant of missing fields because
    Dhan responses can differ between instruments/data intervals.
    """

    symbol = str(row.get("symbol", row.get("SYMBOL", "")))

    direction = str(
        row.get(
            "signal",
            row.get("SIGNAL", "WATCH"),
        )
    ).upper()

    price = float(row.get("price", row.get("PRICE", 0)) or 0)

    ema20 = float(row.get("ema20", row.get("EMA20", 0)) or 0)
    ema50 = float(row.get("ema50", row.get("EMA50", 0)) or 0)
    ema200 = float(row.get("ema200", row.get("EMA200", 0)) or 0)

    vwap = float(row.get("vwap", row.get("VWAP", 0)) or 0)
    rsi = float(row.get("rsi", row.get("RSI", 50)) or 50)

    rvol = float(
        row.get(
            "rvol",
            row.get("RVOL", 0),
        ) or 0
    )

    supertrend = str(
        row.get(
            "supertrend",
            row.get("SUPERTREND", ""),
        )
    ).upper()

    macd = str(
        row.get(
            "macd",
            row.get("MACD", ""),
        )
    ).upper()

    factors = []
    positives = []
    warnings = []
    vetoes = []

    is_buy = direction == "BUY"
    is_sell = direction == "SELL"

    # ---------------------------------------------------------
    # 1. EMA structure - 15 points
    # ---------------------------------------------------------

    if is_buy:
        ema_ok = price > ema20 and ema20 > ema50 and ema50 > ema200
        ema_reason = "Price > EMA20 > EMA50 > EMA200"
    elif is_sell:
        ema_ok = price < ema20 and ema20 < ema50 and ema50 < ema200
        ema_reason = "Price < EMA20 < EMA50 < EMA200"
    else:
        ema_ok = False
        ema_reason = "No directional signal"

    f = _bool_factor(
        "EMA Structure",
        ema_ok,
        15,
        ema_reason,
        "EMA structure is not aligned with signal",
    )

    factors.append(f)

    # ---------------------------------------------------------
    # 2. VWAP - 10 points
    # ---------------------------------------------------------

    if is_buy:
        vwap_ok = price > vwap
    elif is_sell:
        vwap_ok = price < vwap
    else:
        vwap_ok = False

    f = _bool_factor(
        "VWAP",
        vwap_ok,
        10,
        "Price is on the correct side of VWAP",
        "Price is on the wrong side of VWAP",
    )

    factors.append(f)

    # ---------------------------------------------------------
    # 3. RSI - 10 points
    # ---------------------------------------------------------

    if is_buy:
        rsi_ok = 50 <= rsi <= 75
    elif is_sell:
        rsi_ok = 25 <= rsi < 50
    else:
        rsi_ok = False

    f = _bool_factor(
        "RSI",
        rsi_ok,
        10,
        f"RSI supports {direction} ({rsi:.1f})",
        f"RSI does not adequately confirm {direction} ({rsi:.1f})",
    )

    factors.append(f)

    # ---------------------------------------------------------
    # 4. SuperTrend - 10 points
    # ---------------------------------------------------------

    st_buy = "BULL" in supertrend or "UP" in supertrend
    st_sell = "BEAR" in supertrend or "DOWN" in supertrend

    st_ok = (
        (is_buy and st_buy)
        or
        (is_sell and st_sell)
    )

    f = _bool_factor(
        "SuperTrend",
        st_ok,
        10,
        f"SuperTrend confirms {direction}",
        "SuperTrend does not confirm direction",
    )

    factors.append(f)

    # ---------------------------------------------------------
    # 5. MACD - 10 points
    # ---------------------------------------------------------

    macd_buy = "BULL" in macd or "POS" in macd or "UP" in macd
    macd_sell = "BEAR" in macd or "NEG" in macd or "DOWN" in macd

    macd_ok = (
        (is_buy and macd_buy)
        or
        (is_sell and macd_sell)
    )

    f = _bool_factor(
        "MACD",
        macd_ok,
        10,
        f"MACD confirms {direction}",
        "MACD does not confirm direction",
    )

    factors.append(f)

    # ---------------------------------------------------------
    # 6. Volume / RVOL - 15 points
    # ---------------------------------------------------------

    if rvol >= 2.0:
        volume_score = 15
        volume_status = "PASS"
        volume_reason = f"Strong volume confirmation ({rvol:.2f}x)"
    elif rvol >= 1.2:
        volume_score = 10
        volume_status = "PASS"
        volume_reason = f"Acceptable volume confirmation ({rvol:.2f}x)"
    elif rvol >= 0.8:
        volume_score = 5
        volume_status = "WEAK"
        volume_reason = f"Below ideal volume ({rvol:.2f}x)"
        warnings.append("Volume confirmation is weak")
    else:
        volume_score = 0
        volume_status = "FAIL"
        volume_reason = f"Very weak relative volume ({rvol:.2f}x)"
        warnings.append("Very weak volume confirmation")

    factors.append(
        _factor(
            "Volume / RVOL",
            volume_score,
            15,
            volume_status,
            volume_reason,
        )
    )

    # ---------------------------------------------------------
    # 7. MTF - 10 points
    # ---------------------------------------------------------

    if mtf_score is None:
        mtf_score = 0

    mtf_score = max(0, min(100, float(mtf_score)))

    mtf_points = round((mtf_score / 100) * 10, 2)

    if mtf_score >= 80:
        mtf_status = "PASS"
        mtf_reason = f"Strong MTF alignment ({mtf_score:.0f}/100)"
    elif mtf_score >= 60:
        mtf_status = "WEAK"
        mtf_reason = f"Moderate MTF alignment ({mtf_score:.0f}/100)"
        warnings.append("MTF confirmation is not strong")
    else:
        mtf_status = "FAIL"
        mtf_reason = f"Weak MTF alignment ({mtf_score:.0f}/100)"
        warnings.append("MTF confirmation is weak")

    factors.append(
        _factor(
            "Multi-Timeframe",
            mtf_points,
            10,
            mtf_status,
            mtf_reason,
        )
    )

    # ---------------------------------------------------------
    # 8. Market regime - 10 points
    # ---------------------------------------------------------

    market_bias = str(market_bias or "").upper()

    market_aligned = (
        (is_buy and market_bias in ("BULLISH", "POSITIVE", "BUY"))
        or
        (is_sell and market_bias in ("BEARISH", "NEGATIVE", "SELL"))
    )

    market_neutral = market_bias in ("", "NEUTRAL", "SIDEWAYS")

    if market_aligned:
        market_points = 10
        market_status = "PASS"
        market_reason = f"Market regime supports {direction}"
    elif market_neutral:
        market_points = 5
        market_status = "NEUTRAL"
        market_reason = "Market regime is neutral"
    else:
        market_points = 0
        market_status = "FAIL"
        market_reason = f"Market regime conflicts with {direction}"
        warnings.append("Market regime is against the trade")

    factors.append(
        _factor(
            "Market Regime",
            market_points,
            10,
            market_status,
            market_reason,
        )
    )

    # ---------------------------------------------------------
    # 9. Futures OI - 5 points
    # ---------------------------------------------------------

    oi_bias = str(oi_bias or "").upper()

    oi_aligned = (
        (is_buy and oi_bias in ("LONG BUILDUP", "LONG_BUILDUP", "SHORT COVERING"))
        or
        (is_sell and oi_bias in ("SHORT BUILDUP", "SHORT_BUILDUP", "LONG UNWINDING"))
    )

    if oi_aligned:
        oi_points = 5
        oi_status = "PASS"
        oi_reason = f"Futures OI supports {direction}"
    else:
        oi_points = 0
        oi_status = "NEUTRAL"
        oi_reason = "No usable OI confirmation"

    factors.append(
        _factor(
            "Futures OI",
            oi_points,
            5,
            oi_status,
            oi_reason,
        )
    )

    # ---------------------------------------------------------
    # 10. Option structure - 5 points
    # ---------------------------------------------------------

    option_bias = str(option_bias or "").upper()

    option_aligned = (
        (is_buy and option_bias in ("CE", "CALL", "BULLISH", "BUY"))
        or
        (is_sell and option_bias in ("PE", "PUT", "BEARISH", "SELL"))
    )

    if option_aligned:
        option_points = 5
        option_status = "PASS"
        option_reason = f"Option structure supports {direction}"
    else:
        option_points = 0
        option_status = "NEUTRAL"
        option_reason = "No usable option confirmation"

    factors.append(
        _factor(
            "Options",
            option_points,
            5,
            option_status,
            option_reason,
        )
    )

    # ---------------------------------------------------------
    # Aggregate
    # ---------------------------------------------------------

    raw_score = sum(f.score for f in factors)

    # Critical veto:
    # Do not allow a very weak volume situation to remain a
    # high-conviction trade.
    if rvol < 0.5:
        vetoes.append("RVOL below 0.5x - insufficient participation")

    # Critical trend veto
    if is_buy and ema20 and ema50 and ema200:
        if not (price > ema20 and ema20 > ema50):
            vetoes.append("Bullish EMA structure is not confirmed")

    if is_sell and ema20 and ema50 and ema200:
        if not (price < ema20 and ema20 < ema50):
            vetoes.append("Bearish EMA structure is not confirmed")

    # Market conflict is not a hard veto, but it limits conviction.
    if market_bias and not market_aligned and not market_neutral:
        raw_score = min(raw_score, 69)

    # Volume failure caps conviction.
    if rvol < 0.8:
        raw_score = min(raw_score, 69)

    final_score = round(max(0, min(100, raw_score)))

    if vetoes:
        status = "VETO"
    elif final_score >= 85:
        status = "HIGH CONVICTION"
    elif final_score >= 75:
        status = "ACTIONABLE"
    elif final_score >= 60:
        status = "WATCH"
    else:
        status = "LOW CONVICTION"

    for f in factors:
        if f.status == "PASS":
            positives.append(f"{f.name}: {f.reason}")

    return ConvictionResult(
        symbol=symbol,
        direction=direction,
        score=final_score,
        status=status,
        factors=factors,
        vetoes=vetoes,
        positives=positives,
        warnings=warnings,
    )
