"""
FNO COMMANDER - V3 Conviction Engine

The conviction engine combines:
    Technical structure + MTF + market regime + futures OI.

Option-chain confirmation remains on-demand in the UI so the scanner
does not repeatedly consume Dhan option-chain requests.

Score = 100 points:
    EMA structure       15
    VWAP                10
    RSI                 10
    SuperTrend          10
    MACD                10
    RVOL                15
    MTF                 10
    Market regime       10
    Futures OI            5
    Options               5 (reserved/on-demand)

Important:
This is a research/ranking model, not an execution signal.
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


def calculate_conviction(
    row: Dict,
    mtf_score: Optional[float] = None,
    market_bias: Optional[str] = None,
    oi_bias: Optional[str] = None,
    option_bias: Optional[str] = None,
):
    symbol = str(row.get("symbol", row.get("SYMBOL", "")))
    direction = str(row.get("signal", row.get("SIGNAL", "WATCH"))).upper()

    def num(name, default=0.0):
        value = row.get(name, row.get(name.upper(), default))
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    price = num("price")
    ema20 = num("ema20")
    ema50 = num("ema50")
    ema200 = num("ema200")
    vwap = num("vwap")
    rsi = num("rsi", 50)
    rvol = num("rvol")
    supertrend = row.get("supertrend", row.get("SUPERTREND", 0))
    macd = num("macd")
    macd_signal = num("macd_signal")

    factors = []
    positives = []
    warnings = []
    vetoes = []

    is_buy = direction == "BUY"
    is_sell = direction == "SELL"

    # 1. EMA structure — 15
    ema_ok = (
        (is_buy and price > ema20 > ema50 > ema200)
        or (is_sell and price < ema20 < ema50 < ema200)
    )
    factors.append(_factor(
        "EMA Structure", 15 if ema_ok else 0, 15,
        "PASS" if ema_ok else "FAIL",
        "Price/EMA stack aligned with direction"
        if ema_ok else "EMA stack is not fully aligned",
    ))

    # 2. VWAP — 10
    vwap_ok = (
        (is_buy and price > vwap)
        or (is_sell and price < vwap)
    )
    factors.append(_factor(
        "VWAP", 10 if vwap_ok else 0, 10,
        "PASS" if vwap_ok else "FAIL",
        "Price is on the correct side of VWAP"
        if vwap_ok else "Price is on the wrong side of VWAP",
    ))

    # 3. RSI — 10
    rsi_ok = (
        (is_buy and 50 <= rsi <= 75)
        or (is_sell and 25 <= rsi < 50)
    )
    factors.append(_factor(
        "RSI", 10 if rsi_ok else 0, 10,
        "PASS" if rsi_ok else "FAIL",
        f"RSI supports {direction} ({rsi:.1f})"
        if rsi_ok else f"RSI does not confirm {direction} ({rsi:.1f})",
    ))

    # 4. SuperTrend — 10
    try:
        st_bull = float(supertrend) == 1
    except (TypeError, ValueError):
        st_text = str(supertrend).upper()
        st_bull = "BULL" in st_text or "UP" in st_text

    st_ok = st_bull if is_buy else (not st_bull if is_sell else False)
    factors.append(_factor(
        "SuperTrend", 10 if st_ok else 0, 10,
        "PASS" if st_ok else "FAIL",
        f"SuperTrend confirms {direction}"
        if st_ok else "SuperTrend does not confirm direction",
    ))

    # 5. MACD — 10
    macd_bull = macd > macd_signal
    macd_ok = macd_bull if is_buy else (not macd_bull if is_sell else False)
    factors.append(_factor(
        "MACD", 10 if macd_ok else 0, 10,
        "PASS" if macd_ok else "FAIL",
        f"MACD confirms {direction}"
        if macd_ok else "MACD does not confirm direction",
    ))

    # 6. RVOL — 15
    if rvol >= 2.0:
        volume_points, volume_status = 15, "PASS"
        volume_reason = f"Strong participation ({rvol:.2f}x RVOL)"
    elif rvol >= 1.2:
        volume_points, volume_status = 10, "PASS"
        volume_reason = f"Acceptable participation ({rvol:.2f}x RVOL)"
    elif rvol >= 0.8:
        volume_points, volume_status = 5, "WEAK"
        volume_reason = f"Weak participation ({rvol:.2f}x RVOL)"
        warnings.append("Volume confirmation is weak")
    else:
        volume_points, volume_status = 0, "FAIL"
        volume_reason = f"Very weak participation ({rvol:.2f}x RVOL)"
        warnings.append("Very weak volume confirmation")
    factors.append(_factor(
        "Volume / RVOL", volume_points, 15,
        volume_status, volume_reason,
    ))

    # 7. MTF — 10
    mtf = max(0.0, min(100.0, float(mtf_score or 0)))
    mtf_points = round(mtf * 0.10, 2)
    mtf_status = "PASS" if mtf >= 80 else "WEAK" if mtf >= 60 else "FAIL"
    if mtf < 60:
        warnings.append("MTF confirmation is weak")
    factors.append(_factor(
        "Multi-Timeframe", mtf_points, 10, mtf_status,
        f"MTF alignment {mtf:.0f}/100",
    ))

    # 8. Market regime — 10
    bias = str(market_bias or "").upper()
    bull_regimes = {"BULLISH", "MILD BULL", "POSITIVE", "BUY"}
    bear_regimes = {"BEARISH", "MILD BEAR", "NEGATIVE", "SELL"}

    if (is_buy and bias in bull_regimes) or (is_sell and bias in bear_regimes):
        regime_points, regime_status = 10, "PASS"
        regime_reason = f"Market regime supports {direction}"
        regime_aligned = True
    elif bias in {"", "UNKNOWN", "RANGE", "NEUTRAL", "SIDEWAYS"}:
        regime_points, regime_status = 5, "NEUTRAL"
        regime_reason = "Market regime is neutral/ranging"
        regime_aligned = True
    else:
        regime_points, regime_status = 0, "FAIL"
        regime_reason = f"Market regime conflicts with {direction}"
        regime_aligned = False
        warnings.append("Market regime is against the trade")

    factors.append(_factor(
        "Market Regime", regime_points, 10,
        regime_status, regime_reason,
    ))

    # 9. Futures OI — 5
    oi = str(oi_bias or "").upper().replace("_", " ")
    oi_ok = (
        (is_buy and oi in {"LONG BUILDUP", "SHORT COVERING"})
        or (is_sell and oi in {"SHORT BUILDUP", "LONG UNWINDING"})
    )
    factors.append(_factor(
        "Futures OI", 5 if oi_ok else 0, 5,
        "PASS" if oi_ok else "NEUTRAL",
        f"Futures OI supports {direction}" if oi_ok
        else "No aligned futures OI confirmation",
    ))

    # 10. Options — 5 reserved for on-demand confirmation
    opt = str(option_bias or "").upper()
    option_ok = (
        (is_buy and opt in {"CE", "CALL", "BULLISH", "BUY"})
        or (is_sell and opt in {"PE", "PUT", "BEARISH", "SELL"})
    )
    factors.append(_factor(
        "Options", 5 if option_ok else 0, 5,
        "PASS" if option_ok else "ON-DEMAND",
        f"Option structure supports {direction}" if option_ok
        else "Option confirmation loaded on demand",
    ))

    raw_score = sum(f.score for f in factors)

    # Hard vetoes: these stop a setup from being labelled high conviction.
    if direction not in {"BUY", "SELL"}:
        vetoes.append("No directional signal")

    if rvol < 0.5:
        vetoes.append(f"RVOL {rvol:.2f}x is below 0.5x")

    if is_buy and not (price > ema20 > ema50):
        vetoes.append("BUY EMA structure is not confirmed")

    if is_sell and not (price < ema20 < ema50):
        vetoes.append("SELL EMA structure is not confirmed")

    # Conflicting market regime caps, but does not completely veto.
    if not regime_aligned:
        raw_score = min(raw_score, 69)

    # Poor participation cannot become an A-grade trade.
    if rvol < 0.8:
        raw_score = min(raw_score, 69)

    final_score = int(round(max(0, min(100, raw_score))))

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
