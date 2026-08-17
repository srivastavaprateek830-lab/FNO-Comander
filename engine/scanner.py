from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

from engine.conviction import calculate_conviction
from engine.mtf import summarize_timeframe
from indicators.technicals import add_indicators
from engine.scoring import score_technical


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_15m(client, security_id):
    return client.intraday(
        security_id=int(security_id),
        exchange_segment="NSE_EQ",
        instrument="EQUITY",
        interval="15",
        days=60,
        oi=False,
    )


def _fetch_60m(client, security_id):
    return client.intraday(
        security_id=int(security_id),
        exchange_segment="NSE_EQ",
        instrument="EQUITY",
        interval="60",
        days=90,
        oi=False,
    )


def _fetch_future(client, future_security_id):
    if pd.isna(future_security_id):
        return pd.DataFrame()

    return client.intraday(
        security_id=int(future_security_id),
        exchange_segment="NSE_FNO",
        instrument="FUTSTK",
        interval="15",
        days=5,
        oi=True,
    )


def _oi_status(df):
    if df is None or df.empty or "oi" not in df.columns or len(df) < 2:
        return "NEUTRAL"

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price_change = _safe_float(last["close"]) - _safe_float(prev["close"])
    oi_change = _safe_float(last["oi"]) - _safe_float(prev["oi"])

    if price_change > 0 and oi_change > 0:
        return "LONG BUILDUP"
    if price_change < 0 and oi_change > 0:
        return "SHORT BUILDUP"
    if price_change > 0 and oi_change < 0:
        return "SHORT COVERING"
    if price_change < 0 and oi_change < 0:
        return "LONG UNWINDING"
    return "NEUTRAL"


def _scan_one(client, row, market_bias):
    try:
        df = _fetch_15m(client, row["security_id"])

        if df.empty or len(df) < 60:
            return None

        df = add_indicators(df)
        technical = score_technical(df)
        last = df.iloc[-1]

        base = {
            "symbol": row["symbol"],
            "security_id": int(row["security_id"]),
            "future_security_id": row.get("future_security_id"),
            "signal": technical["signal"],
            "technical_score": int(technical["score"]),
            "score": int(technical["score"]),
            "status": "TECHNICAL ONLY",
            "price": _safe_float(last["close"]),
            "rvol": _safe_float(last["rvol"]),
            "rsi": _safe_float(last["rsi"], 50),
            "atr": _safe_float(last["atr"]),
            "ema20": _safe_float(last["ema20"]),
            "ema50": _safe_float(last["ema50"]),
            "ema200": _safe_float(last["ema200"]),
            "vwap": _safe_float(last["vwap"]),
            "supertrend": int(last["supertrend"]),
            "macd": _safe_float(last["macd"]),
            "macd_signal": _safe_float(last["macd_signal"]),
            "reasons": technical["reasons"],
            "risks": technical["risks"],
            "mtf_score": 50,
            "oi_status": "NEUTRAL",
        }

        return base

    except Exception:
        return None


def _enrich_one(client, result, market_bias):
    """Fetch the slower confirmations only for shortlisted candidates."""
    try:
        sid = result["security_id"]

        df60 = _fetch_60m(client, sid)
        mtf60 = summarize_timeframe(df60)

        # Give 60M the strongest weight. 15M is already represented
        # by the technical score. This avoids 3x API multiplication.
        mtf_score = float(mtf60.get("score", 50))

        oi_df = _fetch_future(client, result.get("future_security_id"))
        oi_status = _oi_status(oi_df)

        enriched = dict(result)
        enriched["mtf_score"] = mtf_score
        enriched["oi_status"] = oi_status

        conviction = calculate_conviction(
            enriched,
            mtf_score=mtf_score,
            market_bias=market_bias,
            oi_bias=oi_status,
            option_bias=None,  # option chain remains on-demand
        )

        enriched["score"] = conviction.score
        enriched["status"] = conviction.status
        enriched["conviction_status"] = conviction.status
        enriched["vetoes"] = conviction.vetoes
        enriched["reasons"] = conviction.positives or enriched["reasons"]
        enriched["risks"] = conviction.warnings + conviction.vetoes
        enriched["oi_bias"] = oi_status

        return enriched

    except Exception:
        return result


@st.cache_data(ttl=45, show_spinner=False)
def scan_universe(_client, universe, stage2_count=25, min_score=75, market_bias="RANGE"):
    """
    Two-stage scanner.

    Stage 1:
        one 15M technical pass across the selected Stage-2 candidates.

    Stage 2:
        only the strongest 10 technical candidates receive 60M + futures OI
        enrichment. This keeps Dhan request volume under control.

    Option-chain requests are deliberately NOT made here.
    """

    ids = universe["security_id"].astype(int).tolist()
    quote = _client.quote({"NSE_EQ": ids})

    rows = []
    for _, row in universe.iterrows():
        sid = str(int(row["security_id"]))
        q = quote.get("NSE_EQ", {}).get(sid, {})

        rows.append({
            **row.to_dict(),
            "ltp": q.get("last_price"),
            "net_change": q.get("net_change"),
            "volume": q.get("volume"),
        })

    broad = pd.DataFrame(rows)

    if broad.empty:
        return pd.DataFrame()

    broad["abs_change"] = pd.to_numeric(
        broad["net_change"], errors="coerce"
    ).abs().fillna(0)

    broad["volume"] = pd.to_numeric(
        broad["volume"], errors="coerce"
    ).fillna(0)

    broad["stage1_rank"] = (
        broad["abs_change"].rank(pct=True) * 0.55
        + broad["volume"].rank(pct=True) * 0.45
    )

    candidates = broad.sort_values(
        "stage1_rank", ascending=False
    ).head(int(stage2_count))

    results = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(_scan_one, _client, row, market_bias)
            for _, row in candidates.iterrows()
        ]

        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    if not results:
        return pd.DataFrame()

    # First technical ranking.
    out = pd.DataFrame(results).sort_values(
        ["technical_score", "rvol"],
        ascending=[False, False],
    ).reset_index(drop=True)

    # Only top 10 get expensive 60M + futures-OI enrichment.
    enrich_count = min(10, len(out))
    enriched = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(
                _enrich_one,
                _client,
                row.to_dict(),
                market_bias,
            )
            for _, row in out.head(enrich_count).iterrows()
        ]

        for future in as_completed(futures):
            enriched.append(future.result())

    if enriched:
        enriched_df = pd.DataFrame(enriched)
        untouched = out.iloc[enrich_count:].copy()
        out = pd.concat([enriched_df, untouched], ignore_index=True)

    # Final priority classification.
    def priority(row):
        if row.get("vetoes"):
            return "REJECT"
        score = _safe_float(row.get("score"))
        if score >= 85:
            return "VERY HIGH"
        if score >= min_score:
            return "HIGH"
        if score >= 60:
            return "NORMAL"
        return "LOW"

    out["priority"] = out.apply(priority, axis=1)

    out = out.sort_values(
        ["score", "technical_score", "rvol"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    return out
