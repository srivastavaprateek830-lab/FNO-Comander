from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import streamlit as st

from indicators.technicals import add_indicators
from engine.scoring import score_technical


def _scan_one(client, row):
    try:
        df = client.intraday(
            security_id=int(row["security_id"]),
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            interval="15",
            days=60,
            oi=False,
        )

        if df.empty or len(df) < 60:
            return None

        df = add_indicators(df)
        result = score_technical(df)

        last = df.iloc[-1]

        return {
            "symbol": row["symbol"],
            "security_id": int(row["security_id"]),
            "signal": result["signal"],
            "score": int(result["score"]),
            "price": float(last["close"]),
            "rvol": float(last["rvol"]) if pd.notna(last["rvol"]) else 0.0,
            "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0,
            "atr": float(last["atr"]) if pd.notna(last["atr"]) else 0.0,
            "reasons": result["reasons"],
            "risks": result["risks"],
        }
    except Exception:
        return None


@st.cache_data(ttl=45, show_spinner=False)
def scan_universe(_client, universe, stage2_count=25, min_score=75):
    # Quote snapshot: one request for the broad F&O universe.
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

    # Efficient Stage 1: prioritize movement + liquidity.
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
            pool.submit(_scan_one, _client, row)
            for _, row in candidates.iterrows()
        ]
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results).sort_values(
        ["score", "rvol"], ascending=[False, False]
    ).reset_index(drop=True)

    # Add only qualifying high-conviction signals first, but keep WATCH rows.
    out["priority"] = out["score"].apply(
        lambda x: "HIGH" if x >= min_score else "NORMAL"
    )

    return out
