from __future__ import annotations

import re
from urllib.parse import urlparse

from tracker import http
from tracker.http import FetchError
from tracker.models import Product

NAME = "musinsa"
PAGE_URL = "https://www.musinsa.com/products/{pid}"
LIST_URL = (
    "https://api.musinsa.com/api2/dp/v2/plp/goods"
    "?gf=A&sortCode=DISCOUNT_RATE&brand=musinsastandard&page=1&size=30&caller=FLAGSHIP"
)
_NEXT_PREFIX = "https://api.musinsa.com/"
MAX_PAGES = 20
DEEP_LOOKUP_MAX_PAGES = 150
_ID_RE = re.compile(r"/(?:products|goods)/(\d+)")
_HOSTS = {"musinsa.com", "www.musinsa.com", "m.musinsa.com"}


def _to_product(item: dict) -> Product:
    try:
        pid = str(int(item["goodsNo"]))
        name = item["goodsName"]
        list_price = int(item["normalPrice"])
        price = int(item["price"])
        rate = int(item["saleRate"])
    except (KeyError, TypeError, ValueError) as e:
        raise FetchError("musinsa: malformed item") from e
    if price <= 0:
        raise FetchError(f"musinsa: zero price for {pid}")
    return Product(
        brand=NAME, product_id=pid, name=name, url=PAGE_URL.format(pid=pid),
        image_url=item.get("thumbnail") or "", list_price=list_price, price=price,
        on_sale=rate > 0 and price < list_price,
    )


def _sale_rate(item: dict) -> int:
    try:
        return int(item["saleRate"])
    except (KeyError, TypeError, ValueError) as e:
        raise FetchError("musinsa: malformed item") from e


def _list(raw) -> list[dict]:
    try:
        items = raw["data"]["list"]
    except (KeyError, TypeError) as e:
        raise FetchError("musinsa: malformed list payload") from e
    if not isinstance(items, list):
        raise FetchError("musinsa: malformed list payload")
    return items


def parse_list(raw) -> tuple[list[Product], bool]:
    """Items up to (excluding) the first saleRate == 0 item, and whether one was hit."""
    out: list[Product] = []
    for item in _list(raw):
        if _sale_rate(item) <= 0:
            return out, True
        out.append(_to_product(item))
    return out, False


def parse_sale_page(raw) -> list[Product]:
    return parse_list(raw)[0]


def _next_url(raw) -> str | None:
    try:
        url = raw["data"]["pagination"]["nextPageUrl"]
    except (KeyError, TypeError):
        return None
    if not url:
        return None
    if not isinstance(url, str) or not url.startswith(_NEXT_PREFIX):
        raise FetchError("musinsa: unexpected nextPageUrl")
    return url


class Musinsa:
    name = NAME

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._seen: dict[str, Product] = {}
        self._next_url: str | None = None
        self._pages = 0
        self._reached_end = False

    def matches(self, url: str) -> bool:
        p = urlparse(url)
        return (p.hostname or "").lower() in _HOSTS and bool(_ID_RE.search(p.path))

    def product_id(self, url: str) -> str:
        m = _ID_RE.search(urlparse(url).path)
        if not m:
            raise ValueError(f"not a Musinsa product URL: {url}")
        return str(int(m.group(1)))

    def _fetch_page(self, session, url: str) -> list[Product]:
        try:
            raw = http.polite_get(session, url).json()
        except ValueError as e:
            raise FetchError("musinsa: invalid JSON in list") from e
        items, hit_zero = parse_list(raw)
        nxt = _next_url(raw)
        self._pages += 1
        for p in items:
            self._seen[p.product_id] = p
        self._next_url = nxt
        if hit_zero or nxt is None:
            self._reached_end = True
        return items

    def fetch_sale_items(self, session) -> list[Product]:
        self._reset()
        out: list[Product] = []
        url: str | None = LIST_URL
        for _ in range(MAX_PAGES):
            out.extend(self._fetch_page(session, url))
            if self._reached_end:
                break
            url = self._next_url
        return [p for p in out if p.on_sale]

    def fetch_product(self, session, url: str, sale_items) -> Product | None:
        if sale_items is None:
            raise FetchError("musinsa: sale list unavailable")
        pid = self.product_id(url)
        while True:
            if pid in self._seen:
                return self._seen[pid]
            if self._reached_end:
                return None
            if self._pages >= DEEP_LOOKUP_MAX_PAGES:
                raise FetchError("목록 상한 도달, 확인 불가")
            self._fetch_page(session, self._next_url)


MUSINSA = Musinsa()
