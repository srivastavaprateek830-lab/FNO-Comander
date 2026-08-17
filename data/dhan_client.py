import time
import threading
import requests
import pandas as pd


class DhanAPIError(Exception):
    pass


class DhanClient:
    BASE_URL = "https://api.dhan.co/v2"

    # DhanHQ V2 currently documents:
    #   Data APIs: 5 requests/sec
    #   Quote APIs: 1 request/sec
    #   Option Chain: 1 request / 3 sec
    # We serialize requests per client so Streamlit's concurrent scanner
    # workers cannot create a burst that trips the 805 rate-limit response.
    DATA_MIN_INTERVAL = 0.23
    QUOTE_MIN_INTERVAL = 1.05
    OPTION_MIN_INTERVAL = 3.10

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

        self._rate_lock = threading.Lock()
        self._last_request = {
            "data": 0.0,
            "quote": 0.0,
            "option": 0.0,
        }

    def _wait_for_slot(self, bucket: str, interval: float):
        with self._rate_lock:
            now = time.monotonic()
            wait = interval - (now - self._last_request[bucket])
            if wait > 0:
                time.sleep(wait)
            self._last_request[bucket] = time.monotonic()

    def _post(
        self,
        path: str,
        payload: dict,
        timeout: int = 30,
        bucket: str = "data",
        min_interval: float = DATA_MIN_INTERVAL,
    ):
        url = f"{self.BASE_URL}{path}"

        # A single retry is deliberately used for 429. Repeated immediate
        # retries can make a rate-limit situation worse.
        for attempt in range(2):
            self._wait_for_slot(bucket, min_interval)

            try:
                response = self.session.post(
                    url, json=payload, timeout=timeout
                )
            except requests.RequestException as exc:
                raise DhanAPIError(
                    f"Dhan network error: {exc}"
                ) from exc

            if response.status_code == 429:
                if attempt == 0:
                    time.sleep(2.5)
                    continue

                try:
                    body = response.json()
                except Exception:
                    body = response.text

                raise DhanAPIError(
                    f"Dhan API 429: {body}"
                )

            if response.status_code >= 400:
                try:
                    body = response.json()
                    message = (
                        body.get("errorMessage")
                        or body.get("message")
                        or str(body)
                    )
                except Exception:
                    message = response.text

                raise DhanAPIError(
                    f"Dhan API {response.status_code}: {message}"
                )

            try:
                data = response.json()
            except Exception as exc:
                raise DhanAPIError(
                    "Dhan returned a non-JSON response."
                ) from exc

            if isinstance(data, dict):
                status = str(data.get("status", "")).lower()
                if status in {"failure", "failed"}:
                    raise DhanAPIError(str(data))

            return data

        raise DhanAPIError("Dhan request failed after retry.")

    def ltp(self, instruments: dict):
        return self._post(
            "/marketfeed/ltp",
            instruments,
            bucket="quote",
            min_interval=self.QUOTE_MIN_INTERVAL,
        ).get("data", {})

    def quote(self, instruments: dict):
        return self._post(
            "/marketfeed/quote",
            instruments,
            bucket="quote",
            min_interval=self.QUOTE_MIN_INTERVAL,
        ).get("data", {})

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

        data = self._post(
            "/charts/intraday",
            payload,
            timeout=45,
            bucket="data",
            min_interval=self.DATA_MIN_INTERVAL,
        )

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
            bucket="option",
            min_interval=self.OPTION_MIN_INTERVAL,
        )
        return data.get("data", [])

    def option_chain(self, security_id, underlying_segment, expiry):
        data = self._post(
            "/optionchain",
            {
                "UnderlyingScrip": int(security_id),
                "UnderlyingSeg": underlying_segment,
                "Expiry": expiry,
            },
            timeout=45,
            bucket="option",
            min_interval=self.OPTION_MIN_INTERVAL,
        )
        return data
