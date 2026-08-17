import pandas as pd


def _num(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _oi_change_pct(current, previous):
    previous = _num(previous)
    current = _num(current)
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def analyze_option_chain(raw):
    """
    Normalize Dhan option-chain response into:
      - ATM-window table
      - PCR
      - maximum-OI call/put walls
      - simple directional option bias

    CE and PE legs are deliberately collected independently.
    """

    data = raw.get("data", {}) if isinstance(raw, dict) else {}
    spot = _num(data.get("last_price"))
    oc = data.get("oc", {}) or {}

    rows_by_strike = {}
    calls = []
    puts = []

    for strike_text, legs in oc.items():
        try:
            strike = float(strike_text)
        except (TypeError, ValueError):
            continue

        legs = legs or {}
        ce = legs.get("ce")
        pe = legs.get("pe")

        row = rows_by_strike.setdefault(
            strike,
            {
                "Strike": strike,
                "CE LTP": None,
                "CE OI": None,
                "CE ΔOI %": None,
                "CE IV": None,
                "CE Δ": None,
                "PE LTP": None,
                "PE OI": None,
                "PE ΔOI %": None,
                "PE IV": None,
                "PE Δ": None,
            },
        )

        if ce:
            calls.append(ce)
            row.update({
                "CE LTP": ce.get("last_price"),
                "CE OI": ce.get("oi"),
                "CE ΔOI %": _oi_change_pct(
                    ce.get("oi"), ce.get("previous_oi")
                ),
                "CE IV": ce.get("implied_volatility"),
                "CE Δ": (ce.get("greeks") or {}).get("delta"),
            })

        if pe:
            puts.append(pe)  # FIX: PE was previously not collected.
            row.update({
                "PE LTP": pe.get("last_price"),
                "PE OI": pe.get("oi"),
                "PE ΔOI %": _oi_change_pct(
                    pe.get("oi"), pe.get("previous_oi")
                ),
                "PE IV": pe.get("implied_volatility"),
                "PE Δ": (pe.get("greeks") or {}).get("delta"),
            })

    total_call_oi = sum(_num(x.get("oi")) for x in calls)
    total_put_oi = sum(_num(x.get("oi")) for x in puts)

    pcr = total_put_oi / total_call_oi if total_call_oi else 0.0

    call_wall = max(calls, key=lambda x: _num(x.get("oi"))) if calls else {}
    put_wall = max(puts, key=lambda x: _num(x.get("oi"))) if puts else {}

    if pcr >= 1.20:
        bias = "BULLISH"
    elif pcr <= 0.80:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    table = pd.DataFrame(list(rows_by_strike.values()))

    if not table.empty:
        table["distance"] = (table["Strike"] - spot).abs()
        table = (
            table.sort_values("distance")
            .head(15)
            .sort_values("Strike")
            .drop(columns=["distance"])
            .reset_index(drop=True)
        )

    return {
        "spot": spot,
        "pcr": pcr,
        "call_wall": _num(call_wall.get("strike"), 0) or None,
        "put_wall": _num(put_wall.get("strike"), 0) or None,
        "bias": bias,
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "table": table,
    }
