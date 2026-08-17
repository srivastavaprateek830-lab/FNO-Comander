
def build_trade_plan(signal: str, price: float, atr: float):
    """Create mechanical reference levels from ATR; not investment advice."""
    if price is None or atr is None or atr <= 0 or signal not in {"BUY", "SELL"}:
        return None

    if signal == "BUY":
        sl = price - 1.0 * atr
        t1 = price + 1.5 * atr
        t2 = price + 2.5 * atr
    else:
        sl = price + 1.0 * atr
        t1 = price - 1.5 * atr
        t2 = price - 2.5 * atr

    risk = abs(price - sl)
    rr1 = abs(t1 - price) / risk if risk else 0
    rr2 = abs(t2 - price) / risk if risk else 0

    return {
        "entry": price,
        "sl": sl,
        "target1": t1,
        "target2": t2,
        "rr1": rr1,
        "rr2": rr2,
    }
