"""
FNO COMMANDER - V2B Risk/Veto Engine

Hard filters that prevent technically attractive but structurally
weak setups from being classified as high conviction.
"""


def evaluate_vetoes(
    direction,
    rvol=None,
    price=None,
    vwap=None,
    ema20=None,
    ema50=None,
    supertrend=None,
    market_bias=None,
):
    direction = str(direction or "").upper()
    market_bias = str(market_bias or "").upper()

    vetoes = []

    try:
        rvol = float(rvol) if rvol is not None else None
    except Exception:
        rvol = None

    # Participation veto
    if rvol is not None and rvol < 0.5:
        vetoes.append(
            f"RVOL {rvol:.2f}x is below the minimum participation threshold"
        )

    # VWAP veto
    if price is not None and vwap is not None:
        try:
            price = float(price)
            vwap = float(vwap)

            if direction == "BUY" and price < vwap:
                vetoes.append("BUY candidate is below VWAP")

            if direction == "SELL" and price > vwap:
                vetoes.append("SELL candidate is above VWAP")
        except Exception:
            pass

    # EMA trend veto
    if price is not None and ema20 is not None and ema50 is not None:
        try:
            price = float(price)
            ema20 = float(ema20)
            ema50 = float(ema50)

            if direction == "BUY" and not (price > ema20 > ema50):
                vetoes.append("BUY EMA structure is not aligned")

            if direction == "SELL" and not (price < ema20 < ema50):
                vetoes.append("SELL EMA structure is not aligned")
        except Exception:
            pass

    # SuperTrend veto
    st = str(supertrend or "").upper()

    if direction == "BUY" and st:
        if "BEAR" in st or "DOWN" in st:
            vetoes.append("SuperTrend is bearish")

    if direction == "SELL" and st:
        if "BULL" in st or "UP" in st:
            vetoes.append("SuperTrend is bullish")

    # Market regime warning/veto
    if direction == "BUY" and market_bias == "BEARISH":
        vetoes.append("Market regime is bearish")

    if direction == "SELL" and market_bias == "BULLISH":
        vetoes.append("Market regime is bullish")

    return vetoes
