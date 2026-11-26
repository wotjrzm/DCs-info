import copy
import json
from pathlib import Path

import pytest
import requests

from tracker import http
from tracker.brands import base, uniqlo
from tracker.http import FetchError

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(http, "DELAY_SECONDS", 0)


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.responder(url, kw)


def test_parse_sale_page_returns_only_on_sale_items():
    items = uniqlo.parse_sale_page(load_fixture("uniqlo/sale_list_page1.json"))
    assert items and all(
        p.on_sale and p.brand == "uniqlo" and p.list_price is None for p in items)
    assert not any(p.name.startswith("GU") for p in items)
    assert [p.product_id for p in items] == ["E494543-000"]
    p = items[0]
    assert p.price == 39900
    assert p.url == "https://www.uniqlo.com/kr/ko/products/E494543-000/00"
    assert p.image_url.startswith("https://image.uniqlo.com/") and "494543" in p.image_url


def test_parse_sale_page_skips_items_without_sale_flag():
    raw = load_fixture("uniqlo/sale_list_page1.json")
    for it in raw["result"]["items"]:
        it["representative"]["flags"]["priceFlags"] = []
    assert uniqlo.parse_sale_page(raw) == []


def test_parse_sale_page_malformed_raises():
    with pytest.raises(FetchError):
        uniqlo.parse_sale_page({"status": "ok"})


def test_parse_sale_page_zero_price_raises():
    raw = load_fixture("uniqlo/sale_list_page1.json")
    for it in raw["result"]["items"]:
        it["prices"]["promo"]["value"] = 0
        it["prices"]["base"]["value"] = 0
    with pytest.raises(FetchError):
        uniqlo.parse_sale_page(raw)


def test_parse_product_discounted():
    url = "https://www.uniqlo.com/kr/ko/products/E486821-000/00?colorDisplayCode=07"
    p = uniqlo.parse_product(load_fixture("uniqlo/product_sale.json"), url)
    assert (p.brand, p.product_id, p.name) == ("uniqlo", "E486821-000", "쇼트블루종")
    assert p.price == 79900 and p.list_price is None and p.on_sale is True
    assert p.url == "https://www.uniqlo.com/kr/ko/products/E486821-000/00"


def test_parse_product_not_on_sale_uses_base_price():
    p = uniqlo.parse_product(load_fixture("uniqlo/product_full.json"),
                             "https://www.uniqlo.com/kr/ko/products/E465187-000")
    assert p.price == 7900 and p.on_sale is False and p.list_price is None


def test_parse_product_promo_preferred_over_base():
    raw = load_fixture("uniqlo/product_sale.json")
    raw["result"]["prices"]["promo"]["value"] = 59900
    assert uniqlo.parse_product(raw, "u").price == 59900


def test_parse_product_missing_price_raises_fetch_error():
    raw = copy.deepcopy(load_fixture("uniqlo/product_full.json"))
    raw["result"]["prices"]["base"] = None
    with pytest.raises(FetchError):
        uniqlo.parse_product(raw, "u")
    raw["result"]["prices"] = {"base": {"value": 0}, "promo": None}
    with pytest.raises(FetchError):
        uniqlo.parse_product(raw, "u")
    with pytest.raises(FetchError):
        uniqlo.parse_product({"status": "ok"}, "u")


@pytest.mark.parametrize("url", [
    "https://www.uniqlo.com/kr/ko/products/E486821-000/00?colorDisplayCode=07",
    "https://www.uniqlo.com/kr/ko/products/E486821-000",
    "http://www.uniqlo.com/kr/ko/products/E486821-000/00#reviews",
    "https://uniqlo.com/kr/ko/products/E486821-000/00",
])
def test_product_id_ignores_query_and_variants(url):
    assert uniqlo.UNIQLO.matches(url)
    assert uniqlo.UNIQLO.product_id(url) == "E486821-000"


def test_product_id_bad_url_raises():
    with pytest.raises(ValueError):
        uniqlo.UNIQLO.product_id("https://www.uniqlo.com/kr/ko/")


def test_matches_rejects_other_hosts():
    assert not uniqlo.UNIQLO.matches("https://example.com/kr/ko/products/E486821-000")


def test_fetch_product_uses_detail_api_and_ignores_sale_items():
    s = FakeSession(lambda u, kw: FakeResp(load_fixture("uniqlo/product_sale.json")))
    p = uniqlo.UNIQLO.fetch_product(
        s, "https://www.uniqlo.com/kr/ko/products/E486821-000/00?colorDisplayCode=07", None)
    assert p.price == 79900 and p.on_sale
    assert "/products/E486821-000/price-groups/00/details" in s.calls[0][0]


def test_fetch_product_non_sale_returns_product():
    s = FakeSession(lambda u, kw: FakeResp(load_fixture("uniqlo/product_full.json")))
    p = uniqlo.UNIQLO.fetch_product(
        s, "https://www.uniqlo.com/kr/ko/products/E465187-000", [])
    assert p is not None and p.on_sale is False


def _page(offset, n, total):
    raw = load_fixture("uniqlo/sale_list_page1.json")
    item = [i for i in raw["result"]["items"] if i["productId"] == "E494543-000"][0]
    items = []
    for k in range(n):
        it = copy.deepcopy(item)
        it["productId"] = f"E{500000 + offset + k}-000"
        items.append(it)
    raw["result"]["items"] = items
    raw["result"]["pagination"] = {"total": total, "offset": offset, "count": n}
    return raw


def _offset(url):
    return int(url.split("offset=")[1].split("&")[0])


def test_fetch_sale_items_paginates_until_total():
    s = FakeSession(lambda url, kw: FakeResp(
        _page(_offset(url), min(36, 80 - _offset(url)), 80)))
    items = uniqlo.UNIQLO.fetch_sale_items(s)
    assert len(items) == 80 and len(s.calls) == 3
    assert "flagCodes=discount,limitedOffer" in s.calls[0][0]


def test_fetch_sale_items_stops_on_empty_page():
    s = FakeSession(lambda url, kw: FakeResp(
        _page(_offset(url), 36 if _offset(url) == 0 else 0, 9999)))
    assert len(uniqlo.UNIQLO.fetch_sale_items(s)) == 36
    assert len(s.calls) == 2


def test_fetch_sale_items_caps_at_20_pages():
    s = FakeSession(lambda url, kw: FakeResp(_page(_offset(url), 36, 10**6)))
    uniqlo.UNIQLO.fetch_sale_items(s)
    assert len(s.calls) == 20


def test_polite_get_raises_fetch_error_on_status_and_network():
    with pytest.raises(FetchError):
        http.polite_get(FakeSession(lambda u, kw: FakeResp({}, 500)), "http://x")

    def boom(u, kw):
        raise requests.ConnectionError("down")
    with pytest.raises(FetchError):
        http.polite_get(FakeSession(boom), "http://x")


def test_polite_get_sets_timeout_and_delays(monkeypatch):
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(http, "DELAY_SECONDS", 1.5)
    s = FakeSession(lambda u, kw: FakeResp({}))
    http.polite_get(s, "http://x")
    assert s.calls[0][1]["timeout"] == 20 and slept == [1.5]


def test_make_session_has_browser_ua():
    assert "Mozilla" in http.make_session().headers["User-Agent"]


def test_base_reexports_fetch_error():
    assert base.FetchError is FetchError
