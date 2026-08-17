from io import BytesIO
import pandas as pd
import requests
import streamlit as st


INSTRUMENT_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"


@st.cache_data(ttl=86400)
def load_instrument_master():
    response = requests.get(INSTRUMENT_URL, timeout=60)
    response.raise_for_status()

    df = pd.read_csv(BytesIO(response.content), low_memory=False)

    required = {
        "SECURITY_ID",
        "SEGMENT",
        "INSTRUMENT",
        "SYMBOL_NAME",
        "UNDERLYING_SECURITY_ID",
        "UNDERLYING_SYMBOL",
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Dhan instrument master is missing columns: {sorted(missing)}")

    return df


@st.cache_data(ttl=86400)
def load_fno_universe(instruments: pd.DataFrame):
    # Stock futures are the cleanest definition of the F&O stock universe.
    fut = instruments[
        (instruments["EXCH_ID"].astype(str).str.upper() == "NSE")
        & (instruments["SEGMENT"].astype(str).str.upper() == "D")
        & (instruments["INSTRUMENT"].astype(str).str.upper() == "FUTSTK")
    ].copy()

    if fut.empty:
        raise ValueError("No NSE FUTSTK instruments found in Dhan instrument master.")

    fut["SM_EXPIRY_DATE"] = pd.to_datetime(
        fut.get("SM_EXPIRY_DATE"), errors="coerce"
    )

    # Select nearest active future per underlying.
    today = pd.Timestamp.now().normalize()
    fut = fut[fut["SM_EXPIRY_DATE"].isna() | (fut["SM_EXPIRY_DATE"] >= today)]

    fut = fut.sort_values(["UNDERLYING_SYMBOL", "SM_EXPIRY_DATE"])
    fut = fut.drop_duplicates("UNDERLYING_SYMBOL", keep="first")

    universe = fut[
        [
            "UNDERLYING_SYMBOL",
            "UNDERLYING_SECURITY_ID",
            "SECURITY_ID",
            "SM_EXPIRY_DATE",
        ]
    ].copy()

    universe.columns = [
        "symbol",
        "security_id",
        "future_security_id",
        "future_expiry",
    ]

    universe["security_id"] = pd.to_numeric(
        universe["security_id"], errors="coerce"
    )
    universe["future_security_id"] = pd.to_numeric(
        universe["future_security_id"], errors="coerce"
    )

    # Underlying security IDs are used against NSE_EQ for technical candles.
    universe = universe.dropna(subset=["symbol", "security_id"])
    universe["security_id"] = universe["security_id"].astype(int)
    universe["future_security_id"] = universe["future_security_id"].astype("Int64")

    return universe.sort_values("symbol").reset_index(drop=True)
