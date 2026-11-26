from __future__ import annotations

import re
from urllib.parse import urlparse

from tracker import http
from tracker.http import FetchError
from tracker.models import Product

NAME = "uniqlo"
PAGE_URL = "https://www.uniqlo.com/kr/ko/products/{pid}/00"
LIST_URL = (
    "https://www.uniqlo.com/kr/api/commerce/v5/ko/products"
    "?path=&flagCodes=discount,limitedOffer&limit=36&offset={offset}&httpFailure=true"
)
DETAIL_URL = (
    "https://www.uniqlo.com/kr/api/commerce/v5/ko/products/{pid}/price-groups/00/details"
    "?withPrices=true&withStocks=true&includeModelSize=false&httpFailure=true"
)
MAX_PAGES = 20
SALE_CODES = {"discount", "limitedOffer", "colorSizeLimitedPrice"}
_ID_RE = re.compile(r"/products/(E\d{6}-\d{3})")
_HOSTS = {"uniqlo.com", "www.uniqlo.com"}


def _price(item: dict) -> int:
    try:
        prices = item["prices"]
        promo = prices.get("promo")
        value = promo["value"] if promo else prices["base"]["value"]
        value = int(value)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise FetchError(f"uniqlo: missing price for {item.get('productId')}") from e
    if value <= 0:
        raise FetchError(f"uniqlo: zero price for {item.get('productId')}")
    return value


def _on_sale(item: dict) -> bool:
    try:
        flags = item["representative"]["flags"]["priceFlags"] or []
    except (KeyError, TypeError):
        return False
    return any(f.get("code") in SALE_CODES for f in flags)


def _image(item: dict) -> str:
    main = (item.get("images") or {}).get("main") or {}
    for c in item.get("colors") or []:
        img = (main.get(c.get("displayCode")) or {}).get("image")
        if img:
            return img
    for v in main.values():
        if v.get("image"):
            return v["image"]
    return ""


def _to_product(item: dict) -> Product:
    try:
        pid, name = item["productId"], item["name"]
    except (KeyError, TypeError) as e:
        raise FetchError("uniqlo: malformed item") from e
    return Product(
        brand=NAME, product_id=pid, name=name, url=PAGE_URL.format(pid=pid),
        image_url=_image(item), list_price=None, price=_price(item),
        on_sale=_on_sale(item),
    )


def _items(raw) -> list[dict]:
    try:
        items = raw["result"]["items"]
    except (KeyError, TypeError) as e:
        raise FetchError("uniqlo: malformed list payload") from e
    if not isinstance(items, list):
        raise FetchError("uniqlo: malformed list payload")
    return items


def parse_sale_page(raw) -> list[Product]:
    out = []
    for item in _items(raw):
        if str(item.get("name", "")).startswith("GU") or not _on_sale(item):
            continue
        out.append(_to_product(item))
    return out


def parse_product(raw, url: str) -> Product:
    try:
        item = raw["result"]
    except (KeyError, TypeError) as e:
        raise FetchError("uniqlo: malformed product payload") from e
    if not isinstance(item, dict):
        raise FetchError("uniqlo: malformed product payload")
    return _to_product(item)


class _Uniqlo:
    name = NAME

    def matches(self, url: str) -> bool:
        p = urlparse(url)
        return (p.hostname or "").lower() in _HOSTS and bool(_ID_RE.search(p.path))

    def product_id(self, url: str) -> str:
        m = _ID_RE.search(urlparse(url).path)
        if not m:
            raise ValueError(f"not a Uniqlo product URL: {url}")
        return m.group(1)

    def fetch_sale_items(self, session) -> list[Product]:
        out: list[Product] = []
        offset = 0
        for _ in range(MAX_PAGES):
            try:
                raw = http.polite_get(session, LIST_URL.format(offset=offset)).json()
            except ValueError as e:
                raise FetchError("uniqlo: invalid JSON in list") from e
            items = _items(raw)
            if not items:
                break
            out.extend(parse_sale_page(raw))
            offset += len(items)
            try:
                total = raw["result"]["pagination"]["total"]
            except (KeyError, TypeError):
                total = None
            if total is not None and offset >= total:
                break
        return out

    def fetch_product(self, session, url: str, sale_items) -> Product | None:
        pid = self.product_id(url)
        try:
            raw = http.polite_get(session, DETAIL_URL.format(pid=pid)).json()
        except ValueError as e:
            raise FetchError(f"uniqlo: invalid JSON for {pid}") from e
        return parse_product(raw, url)


UNIQLO = _Uniqlo()
