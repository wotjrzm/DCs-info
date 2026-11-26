from __future__ import annotations

import time

import requests

DELAY_SECONDS = 1.5
TIMEOUT_SECONDS = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class FetchError(Exception):
    pass


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    return s


def polite_get(session, url: str, **kw):
    """GET after a courtesy delay; any network error or non-2xx -> FetchError."""
    if DELAY_SECONDS:
        time.sleep(DELAY_SECONDS)
    kw.setdefault("timeout", TIMEOUT_SECONDS)
    try:
        resp = session.get(url, **kw)
    except requests.RequestException as e:
        raise FetchError(f"request failed: {url}: {e}") from e
    if not 200 <= resp.status_code < 300:
        raise FetchError(f"HTTP {resp.status_code}: {url}")
    return resp
