import time
import requests

class HttpClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def get(self, path: str, params: dict | None = None, retries: int = 2) -> dict:
        url = f"{self.base_url}{path}"
        last_err = None
        for i in range(retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                time.sleep(0.5 * (i + 1))
        raise last_err
