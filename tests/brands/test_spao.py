import copy
import json
from pathlib import Path

import pytest

from tracker import http
from tracker.brands import BRANDS, brand_for_url, spao
from tracker.http import FetchError

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "spao"
SALE_URL = "https://www.spao.com/i/item?itemNo=2607013428&lowerVendNo=LV26000002"
FULL_URL = "https://www.spao.com/i/item?itemNo=2611025016&lowerVendNo=LV26000002"


def load_json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def load_html(name):
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(http, "DELAY_SECONDS", 0)


class FakeResp:
    def __init__(self, data=None, status=200, text=None):
        self._data, self.status_code = data, status
        self.text = text if text is not None else json.dumps(data)

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeSession:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.responder(url, kw)


def test_parse_sale_page_returns_only_on_sale_items():
    raw = load_json("sale_list_page1.json")
    items = spao.parse_sale_page(raw)
    assert items and all(p.on_sale and p.brand == "spao" and p.list_price > p.price for p in items)
    assert len(items) == len(raw["data"])
    p = items[0]
    assert (p.product_id, p.list_price, p.price) == ("2607013428", 59900, 53910)
    assert p.url == SALE_URL
    assert p.name.startswith("[씬라이트]")
    assert p.image_url == "https://spao-item.elandrs.com/" + raw["data"][0]["representImagePath"]


def test_parse_sale_page_skips_full_price_items():
    raw = load_json("sale_list_page1.json")
    for it in raw["data"]:
        it["sellprice"] = it["orgSellprice"]
    assert spao.parse_sale_page(raw) == []


@pytest.mark.parametrize("bad", [{"resultCode": "200"}, {"data": {}}, [], None])
def test_parse_sale_page_malformed_raises(bad):
    with pytest.raises(FetchError):
        spao.parse_sale_page(bad)


@pytest.mark.parametrize("elem", ["x", None, 5, ["a"]])
def test_parse_sale_page_non_dict_element_raises(elem):
    with pytest.raises(FetchError):
        spao.parse_sale_page({"data": [elem]})


@pytest.mark.parametrize("mutate", [
    lambda it: it.pop("sellprice"),
    lambda it: it.__setitem__("sellprice", 0),
    lambda it: it.__setitem__("orgSellprice", None),
    lambda it: it.pop("itemNo"),
])
def test_parse_sale_page_missing_or_zero_price_raises(mutate):
    raw = load_json("sale_list_page1.json")
    mutate(raw["data"][0])
    with pytest.raises(FetchError):
        spao.parse_sale_page(raw)


def test_parse_product_discounted():
    p = spao.parse_product(load_html("product_sale.html"), SALE_URL + "&utm_source=x")
    assert (p.brand, p.product_id) == ("spao", "2607013428")
    assert p.name == "[씬라이트] 후드 재킷_SPJPG4TC24"
    assert (p.list_price, p.price, p.on_sale) == (59900, 53910, True)
    assert p.url == SALE_URL
    assert p.image_url.startswith("https://spao-item.elandrs.com/")


def test_parse_product_full_price_not_on_sale():
    p = spao.parse_product(load_html("product_full.html"), FULL_URL)
    assert (p.list_price, p.price, p.on_sale) == (49900, 49900, False)


def test_parse_product_requires_uppercase_p_keys():
    html = load_html("product_sale.html").replace("orgSellPrice", "orgSellprice")
    with pytest.raises(FetchError):
        spao.parse_product(html, SALE_URL)


def test_parse_product_missing_lowervend_in_url_taken_from_page():
    p = spao.parse_product(load_html("product_sale.html"),
                           "https://www.spao.com/i/item?itemNo=2607013428")
    assert p.url == SALE_URL


def test_parse_product_malformed_raises():
    with pytest.raises(FetchError):
        spao.parse_product("<html></html>", SALE_URL)
    zero = load_html("product_sale.html").replace('"sellPrice":53910', '"sellPrice":0')
    with pytest.raises(FetchError):
        spao.parse_product(zero, SALE_URL)
    with pytest.raises(FetchError):
        spao.parse_product('<script>var item={"priceInfo":{broken}};</script>', SALE_URL)


@pytest.mark.parametrize("url", [
    "https://www.spao.com/i/item?itemNo=2607013428&lowerVendNo=LV26000002",
    "https://www.spao.com/i/item?lowerVendNo=LV26000002&itemNo=2607013428",
    "https://www.spao.com/i/item?itemNo=2607013428&lowerVendNo=LV26000002&utm_source=a&utm_medium=b",
    "http://www.spao.com/i/item?itemNo=2607013428#reviews",
    "https://spao.com/i/item?itemNo=2607013428",
    "https://m.spao.com/i/item?itemNo=2607013428&lowerVendNo=LV26000002",
])
def test_product_id_ignores_variants(url):
    assert spao.SPAO.matches(url)
    assert spao.SPAO.product_id(url) == "2607013428"


@pytest.mark.parametrize("url", [
    "https://example.com/i/item?itemNo=2607013428",
    "https://www.spao.com/i/item?lowerVendNo=LV26000002",
    "https://www.spao.com/",
    "https://www.spao.com.evil.com/i/item?itemNo=2607013428",
])
def test_non_spao_or_missing_item_no(url):
    assert not spao.SPAO.matches(url)
    with pytest.raises(ValueError):
        spao.SPAO.product_id(url)


def test_brand_for_url_and_registry():
    assert brand_for_url(SALE_URL).name == "spao"
    assert "spao" in [b.name for b in BRANDS]
    assert brand_for_url("https://www.uniqlo.com/kr/ko/products/E486821-000/00").name == "uniqlo"
    assert brand_for_url("https://www.musinsa.com/products/2463944").name == "musinsa"


def test_fetch_product_canonicalizes_url_and_ignores_sale_items():
    s = FakeSession(lambda u, kw: FakeResp(text=load_html("product_sale.html")))
    p = spao.SPAO.fetch_product(s, SALE_URL + "&utm_source=x#frag", None)
    assert p.price == 53910 and p.on_sale
    assert s.calls[0][0] == SALE_URL


def test_fetch_product_non_sale_returns_product():
    s = FakeSession(lambda u, kw: FakeResp(text=load_html("product_full.html")))
    p = spao.SPAO.fetch_product(s, FULL_URL, [])
    assert p is not None and p.on_sale is False


def test_fetch_product_http_error_is_fetch_error():
    s = FakeSession(lambda u, kw: FakeResp(text="", status=503))
    with pytest.raises(FetchError):
        spao.SPAO.fetch_product(s, SALE_URL, None)


def _page_no(url):
    return int(url.split("page=")[1].split("&")[0])


def _items(page, n):
    base = load_json("sale_list_page1.json")["data"][0]
    out = []
    for k in range(n):
        it = copy.deepcopy(base)
        it["itemNo"] = str(3000000000 + page * 1000 + k)
        out.append(it)
    return out


def _resp(page, n):
    return FakeResp({"resultCode": "200", "resultMessage": "success", "data": _items(page, n)})


def test_fetch_sale_items_paginates_until_short_page():
    sizes = {1: 100, 2: 100, 3: 40}
    s = FakeSession(lambda url, kw: _resp(_page_no(url), sizes[_page_no(url)]))
    items = spao.SPAO.fetch_sale_items(s)
    assert len(items) == 240 and len(s.calls) == 3
    assert "dispLctgNo=2605000005" in s.calls[0][0] and "size=100" in s.calls[0][0]
    assert "/api/item/sale" in s.calls[0][0]


def test_fetch_sale_items_stops_on_empty_page():
    s = FakeSession(lambda url, kw: _resp(_page_no(url), 100 if _page_no(url) == 1 else 0))
    assert len(spao.SPAO.fetch_sale_items(s)) == 100
    assert len(s.calls) == 2


def test_fetch_sale_items_caps_at_20_pages():
    s = FakeSession(lambda url, kw: _resp(_page_no(url), 100))
    spao.SPAO.fetch_sale_items(s)
    assert len(s.calls) == 20


def test_fetch_sale_items_dedupes_by_product_id():
    s = FakeSession(lambda url, kw: _resp(1, 100 if _page_no(url) == 1 else 5))
    items = spao.SPAO.fetch_sale_items(s)
    assert len(items) == 100 and len({p.product_id for p in items}) == 100


def test_fetch_sale_items_invalid_json_raises():
    s = FakeSession(lambda url, kw: FakeResp(text="<html>"))
    with pytest.raises(FetchError):
        spao.SPAO.fetch_sale_items(s)
