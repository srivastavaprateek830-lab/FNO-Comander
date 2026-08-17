import pandas as pd


def _oi_change_pct(current, previous):
    if previous in (None, 0):
        return 0.0
    return (current - previous) / previous * 100.0


def analyze_option_chain(raw):
    data = raw.get("data", {})
    spot = float(data.get("last_price", 0))
    oc = data.get("oc", {})

    rows = []
    calls = []
    puts = []

    for strike_text, legs in oc.items():
        strike = float(strike_text)

        ce = legs.get("ce")
        pe = legs.get("pe")

        if ce:
            calls.append(ce)
            rows.append({
                "Strike": strike,
                "CE LTP": ce.get("last_price"),
                "CE OI": ce.get("oi"),
                "CE ΔOI %": _oi_change_pct(ce.get("oi", 0), ce.get("previous_oi", 0)),
                "CE IV": ce.get("implied_volatility"),
                "CE Δ": ce.get("greeks", {}).get("delta"),
                "PE LTP": None,
                "PE OI": None,
                "PE ΔOI %": None,
                "PE IV": None,
                "PE Δ": None,
            })

        if pe:
            existing = next((x for x in rows if x["Strike"] == strike), None)
            if existing:
                existing.update({
                    "PE LTP": pe.get("last_price"),
                    "PE OI": pe.get("oi"),
                    "PE ΔOI %": _oi_change_pct(pe.get("oi", 0), pe.get("previous_oi", 0)),
                    "PE IV": pe.get("implied_volatility"),
                    "PE Δ": pe.get("greeks", {}).get("delta"),
                })
            else:
                rows.append({
                    "Strike": strike,
                    "CE LTP": None,
                    "CE OI": None,
                    "CE ΔOI %": None,
                    "CE IV": None,
                    "CE Δ": None,
                    "PE LTP": pe.get("last_price"),
                    "PE OI": pe.get("oi"),
                    "PE ΔOI %": _oi_change_pct(pe.get("oi", 0), pe.get("previous_oi", 0)),
                    "PE IV": pe.get("implied_volatility"),
                    "PE Δ": pe.get("greeks", {}).get("delta"),
                })

    total_call_oi = sum((x.get("oi") or 0) for x in calls)
    total_put_oi = sum((x.get("oi") or 0) for x in puts)

    pcr = total_put_oi / total_call_oi if total_call_oi else 0.0

    call_wall = max(calls, key=lambda x: x.get("oi", 0)) if calls else {}
    put_wall = max(puts, key=lambda x: x.get("oi", 0)) if puts else {}

    table = pd.DataFrame(rows).sort_values("Strike")
    if not table.empty:
        # Show a practical ATM window rather than every strike.
        table["distance"] = (table["Strike"] - spot).abs()
        table = table.sort_values("distance").head(15).sort_values("Strike")
        table = table.drop(columns=["distance"])

    return {
        "spot": spot,
        "pcr": pcr,
        "call_wall": call_wall.get("strike"),
        "put_wall": put_wall.get("strike"),
        "table": table,
    }
