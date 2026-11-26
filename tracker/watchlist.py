from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset({"fbclid", "gclid", "igshid"})


def _is_tracking(name: str) -> bool:
    return name.startswith("utm_") or name in TRACKING_PARAMS


def _normalize(token: str) -> str:
    parts = urlsplit(token)
    pairs = sorted(
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking(name)
    )
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(pairs),
            "",
        )
    )


def parse_watchlist(text: str) -> list[str]:
    urls: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(_normalize(line.split()[0]))
    return list(dict.fromkeys(urls))
