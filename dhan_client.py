import time
import requests
import pandas as pd


class DhanAPIError(Exception):
    pass


class DhanClient:
    BASE_URL = "https://api.dhan.co/v2"

    def __init__(self, client_id: str, access_token: str):
        self.client_id = str(client_id)
        self.access_token = str(access_token)
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "access-token": self.access_token,
            "client-id": self.client_id,
        })

    def _post(self, path: str, payload: dict, timeout: int = 30):
        url = f"{self.BASE_URL}{path}"
        try:
            response = self.session.post(url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise DhanAPIError(f"Dhan network error: {exc}") from exc

        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("errorMessage") or body.get("message") or str(body)
            except Exception:
                message = response.text
            raise DhanAPIError(f"Dhan API {response.status_code}: {message}")

        try:
            data = response.json()
        except Exception as exc:
            raise DhanAPIError("Dhan returned a non-JSON response.") from exc

        if isinstance(data, dict) and data.get("status") == "failure":
            raise DhanAPIError(str(data))

        return data

    def ltp(self, instruments: dict):
        return self._post("/marketfeed/ltp", instruments).get("data", {})

    def quote(self, instruments: dict):
        return self._post("/marketfeed/quote", instruments).get("data", {})

    def intraday(
        self,
        security_id,
        exchange_segment="NSE_EQ",
        instrument="EQUITY",
        interval="15",
        days=60,
        oi=False,
    ):
        end = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
        start = end - pd.Timedelta(days=days)

        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": bool(oi),
            "fromDate": start.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": end.strftime("%Y-%m-%d %H:%M:%S"),
        }

        data = self._post("/charts/intraday", payload, timeout=45)

        if not data:
            return pd.DataFrame()

        d = data.get("data", data)
        if not d or "timestamp" not in d:
            return pd.DataFrame()

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(d["timestamp"], unit="s"),
            "open": d["open"],
            "high": d["high"],
            "low": d["low"],
            "close": d["close"],
            "volume": d["volume"],
        })

        if "oi" in d:
            df["oi"] = d["oi"]

        return df.sort_values("timestamp").reset_index(drop=True)

    def option_expiries(self, security_id, underlying_segment="NSE_EQ"):
        data = self._post(
            "/optionchain/expirylist",
            {
                "UnderlyingScrip": int(security_id),
                "UnderlyingSeg": underlying_segment,
            },
        )
        return data.get("data", [])

    def option_chain(self, security_id, underlying_segment, expiry):
        # Dhan limits unique option-chain requests to one every 3 seconds.
        time.sleep(3.05)
        return self._post(
            "/optionchain",
            {
                "UnderlyingScrip": int(security_id),
                "UnderlyingSeg": underlying_segment,
                "Expiry": expiry,
            },
            timeout=45,
        )
