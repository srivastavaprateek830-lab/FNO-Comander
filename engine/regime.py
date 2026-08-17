import pandas as pd


def market_regime(market_df: pd.DataFrame):
    if market_df.empty:
        return {"label": "UNKNOWN", "score": 50}

    changes = pd.to_numeric(market_df["change"], errors="coerce").dropna()
    if changes.empty:
        return {"label": "UNKNOWN", "score": 50}

    avg = changes.mean()

    if avg > 0.75:
        return {"label": "BULLISH", "score": 80}
    if avg > 0.20:
        return {"label": "MILD BULL", "score": 65}
    if avg < -0.75:
        return {"label": "BEARISH", "score": 20}
    if avg < -0.20:
        return {"label": "MILD BEAR", "score": 35}

    return {"label": "RANGE", "score": 50}
