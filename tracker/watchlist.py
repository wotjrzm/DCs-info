from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def _normalize(token: str) -> str:
    parts = urlsplit(token)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def parse_watchlist(text: str) -> list[str]:
    urls: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(_normalize(line.split()[0]))
    return list(dict.fromkeys(urls))
