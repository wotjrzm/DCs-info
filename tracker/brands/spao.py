from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlencode, urlparse

from tracker import http
from tracker.http import FetchError
from tracker.models import Product

NAME = "spao"
PAGE_URL = "https://www.spao.com/i/item"
LIST_URL = (
    "https://www.spao.com/api/item/sale"
    "?size={size}&dispLctgNo=2605000005&sort=40&page={page}"
)
PAGE_SIZE = 100
MAX_PAGES = 20
IMAGE_HOST = "https://spao-item.elandrs.com/"
_HOSTS = {"spao.com", "www.spao.com", "m.spao.com"}
_ITEM_NO_RE = re.compile(r"^\d+$")
_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_PRICE_INFO_RE = re.compile(r'"priceInfo"\s*:\s*(\{[^{}]*\})')


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def _item_no(url: str) -> str | None:
    p = urlparse(url)
    if (p.hostname or "").lower() not in _HOSTS:
        return None
    vals = _query(url).get("itemNo") or []
    return vals[0] if vals and _ITEM_NO_RE.match(vals[0]) else None


def _canonical_url(item_no: str, lower_vend: str | None) -> str:
    params = {"itemNo": item_no}
    if lower_vend:
        params["lowerVendNo"] = lower_vend
    return f"{PAGE_URL}?{urlencode(params)}"


def _positive_int(value, what: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as e:
        raise FetchError(f"spao: missing {what}") from e
    if n <= 0:
        raise FetchError(f"spao: zero {what}")
    return n


def _image(path) -> str:
    if not path or not isinstance(path, str):
        return ""
    if path.startswith("http"):
        return path
    return IMAGE_HOST + path.lstrip("/")


def _list_item_to_product(item) -> Product:
    if not isinstance(item, dict):
        raise FetchError("spao: malformed list item")
    try:
        item_no, name = str(item["itemNo"]), item["itemName"]
    except KeyError as e:
        raise FetchError("spao: malformed list item") from e
    if not _ITEM_NO_RE.match(item_no):
        raise FetchError("spao: malformed itemNo")
    list_price = _positive_int(item.get("orgSellprice"), f"list price for {item_no}")
    price = _positive_int(item.get("sellprice"), f"price for {item_no}")
    return Product(
        brand=NAME, product_id=item_no, name=name,
        url=_canonical_url(item_no, item.get("lowerVendNo") or None),
        image_url=_image(item.get("representImagePath")),
        list_price=list_price, price=price, on_sale=price < list_price,
    )


def _data(raw) -> list:
    try:
        data = raw["data"]
    except (KeyError, TypeError) as e:
        raise FetchError("spao: malformed list payload") from e
    if not isinstance(data, list):
        raise FetchError("spao: malformed list payload")
    return data


def parse_sale_page(raw) -> list[Product]:
    products = [_list_item_to_product(i) for i in _data(raw)]
    return [p for p in products if p.on_sale]


def _ld_product(text: str) -> dict:
    for block in _LD_RE.findall(text):
        try:
            doc = json.loads(block)
        except ValueError:
            continue
        nodes = doc.get("@graph", [doc]) if isinstance(doc, dict) else []
        for n in nodes:
            if isinstance(n, dict) and n.get("@type") == "Product":
                return n
    return {}


def parse_product(raw, url: str) -> Product:
    """raw is the detail page HTML text."""
    if not isinstance(raw, str):
        raise FetchError("spao: malformed product page")
    item_no = _item_no(url)
    if item_no is None:
        raise FetchError(f"spao: no itemNo in {url}")
    m = _PRICE_INFO_RE.search(raw)
    if not m:
        raise FetchError(f"spao: no priceInfo for {item_no}")
    try:
        info = json.loads(m.group(1))
    except ValueError as e:
        raise FetchError(f"spao: bad priceInfo for {item_no}") from e
    # Detail JSON uses capital-P keys (orgSellPrice/sellPrice), unlike the list.
    list_price = _positive_int(info.get("orgSellPrice"), f"list price for {item_no}")
    price = _positive_int(info.get("sellPrice"), f"price for {item_no}")

    ld = _ld_product(raw)
    lower_vend = (_query(url).get("lowerVendNo") or [None])[0]
    if not lower_vend:
        ident = html.unescape(str(ld.get("@id") or ""))
        lower_vend = (_query(ident).get("lowerVendNo") or [None])[0]
    image = ld.get("image")
    if isinstance(image, list):
        image = image[0] if image else ""
    return Product(
        brand=NAME, product_id=item_no, name=str(ld.get("name") or ""),
        url=_canonical_url(item_no, lower_vend), image_url=_image(image),
        list_price=list_price, price=price, on_sale=price < list_price,
    )


class _Spao:
    name = NAME

    def matches(self, url: str) -> bool:
        return _item_no(url) is not None

    def product_id(self, url: str) -> str:
        item_no = _item_no(url)
        if item_no is None:
            raise ValueError(f"not a SPAO product URL: {url}")
        return item_no

    def fetch_sale_items(self, session) -> list[Product]:
        out: dict[str, Product] = {}
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL.format(size=PAGE_SIZE, page=page)
            try:
                raw = http.polite_get(session, url).json()
            except ValueError as e:
                raise FetchError("spao: invalid JSON in list") from e
            data = _data(raw)
            if not data:
                break
            for p in parse_sale_page(raw):
                out.setdefault(p.product_id, p)
            if len(data) < PAGE_SIZE:
                break
        return list(out.values())

    def fetch_product(self, session, url: str, sale_items) -> Product:
        item_no = self.product_id(url)
        lower_vend = (_query(url).get("lowerVendNo") or [None])[0]
        text = http.polite_get(session, _canonical_url(item_no, lower_vend)).text
        return parse_product(text, url)


SPAO = _Spao()
