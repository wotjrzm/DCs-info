import copy
import json
from pathlib import Path

import pytest

from tracker import http
from tracker.brands import brand_for_url, musinsa
from tracker.http import FetchError

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NEXT = "https://api.musinsa.com/api2/dp/v2/plp/goods?page={n}&hmacId=SIG{n}"


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
        self.calls.append(url)
        return self.responder(url)


def item(goods_no, sale_rate=30, normal=10000):
    base = copy.deepcopy(load_fixture("musinsa/sale_list_discount_page1.json")["data"]["list"][0])
    price = normal * (100 - sale_rate) // 100
    base.update(goodsNo=goods_no, saleRate=sale_rate, normalPrice=normal, price=price,
                goodsLinkUrl=f"https://www.musinsa.com/products/{goods_no}")
    return base


def page(n, items, has_next=True):
    return {"data": {"list": items, "pagination": {
        "page": n, "nextPageUrl": NEXT.format(n=n + 1) if has_next else None,
        "hasNext": has_next}}}


def synthetic(last_page, zero_at=None, per_page=2):
    """Pages 1..last_page; goodsNo = page*100+i; saleRate 0 from page `zero_at` on."""
    def responder(url):
        n = 1 if "page=" not in url else int(url.split("page=")[1].split("&")[0])
        rate = 0 if zero_at is not None and n >= zero_at else 30
        items = [item(n * 100 + i, rate) for i in range(per_page)]
        return FakeResp(page(n, items, has_next=n < last_page))
    return responder


def test_parse_page_fixture():
    items = musinsa.parse_sale_page(load_fixture("musinsa/sale_list_discount_page1.json"))
    assert [p.product_id for p in items] == ["2463944", "1803592", "3455327", "3455326"]
    p = items[0]
    assert (p.brand, p.list_price, p.price, p.on_sale) == ("musinsa", 59900, 5990, True)
    assert p.url == "https://www.musinsa.com/products/2463944"
    assert p.image_url.startswith("https://image.msscdn.net/")


def test_parse_stops_at_sale_rate_zero():
    items, hit_zero = musinsa.parse_list(load_fixture("musinsa/sale_list_discount_tail.json"))
    assert [p.product_id for p in items] == ["1388934", "1283757", "1260384"]
    assert hit_zero is True


def test_malformed_payload_raises():
    with pytest.raises(FetchError):
        musinsa.parse_list({"data": {}})
    with pytest.raises(FetchError):
        musinsa.parse_list({"data": {"list": [{"goodsNo": 1}]}})


@pytest.mark.parametrize("url", [
    "https://www.musinsa.com/products/2463944",
    "https://m.musinsa.com/products/2463944",
    "https://www.musinsa.com/app/goods/2463944",
    "https://www.musinsa.com/products/2463944?utm=x#top",
])
def test_product_id_variants(url):
    m = musinsa.Musinsa()
    assert m.matches(url) and m.product_id(url) == "2463944"
    assert brand_for_url(url).name == "musinsa"


def test_matches_rejects_other():
    m = musinsa.Musinsa()
    assert not m.matches("https://www.musinsa.com/brand/musinsastandard")
    assert not m.matches("https://example.com/products/123")
    with pytest.raises(ValueError):
        m.product_id("https://example.com/x")


def test_fetch_sale_items_first_url_and_signed_next():
    s = FakeSession(synthetic(last_page=3))
    items = musinsa.Musinsa().fetch_sale_items(s)
    assert "brand=musinsastandard" in s.calls[0] and "sortCode=DISCOUNT_RATE" in s.calls[0]
    assert s.calls[1:] == [NEXT.format(n=2), NEXT.format(n=3)]
    assert len(items) == 6


def test_fetch_sale_items_caps_at_20_pages():
    s = FakeSession(synthetic(last_page=100))
    assert len(musinsa.Musinsa().fetch_sale_items(s)) == 40
    assert len(s.calls) == musinsa.MAX_PAGES == 20


def test_fetch_sale_items_stops_at_zero_and_returns_only_on_sale():
    raw = [page(1, [item(1), item(2)]), load_fixture("musinsa/sale_list_discount_tail.json")]
    s = FakeSession(lambda url: FakeResp(raw[len(s.calls) - 1]))
    items = musinsa.Musinsa().fetch_sale_items(s)
    assert [p.product_id for p in items] == ["1", "2", "1388934", "1283757", "1260384"]
    assert all(p.on_sale for p in items)


def test_fetch_error_on_http_failure():
    s = FakeSession(lambda url: FakeResp({}, status=403))
    with pytest.raises(FetchError):
        musinsa.Musinsa().fetch_sale_items(s)


def test_fetch_product_none_sale_items_raises():
    with pytest.raises(FetchError):
        musinsa.Musinsa().fetch_product(
            FakeSession(synthetic(3)), "https://www.musinsa.com/products/1", None)


def test_fetch_product_found_in_seen_without_fetching():
    s = FakeSession(synthetic(last_page=5))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    n = len(s.calls)
    p = m.fetch_product(s, "https://m.musinsa.com/products/201", items)
    assert p.product_id == "201" and p.on_sale and len(s.calls) == n


def test_fetch_product_found_after_page_20():
    s = FakeSession(synthetic(last_page=100))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    p = m.fetch_product(s, "https://www.musinsa.com/products/2500", items)  # page 25
    assert p.product_id == "2500" and p.on_sale and p.price == 7000
    assert len(s.calls) == 25


def test_two_watched_items_reuse_fetched_pages():
    s = FakeSession(synthetic(last_page=100))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    m.fetch_product(s, "https://www.musinsa.com/products/3000", items)  # page 30
    assert len(s.calls) == 30
    assert m.fetch_product(s, "https://www.musinsa.com/products/2100", items).product_id == "2100"
    assert len(s.calls) == 30
    m.fetch_product(s, "https://www.musinsa.com/products/3200", items)  # page 32
    assert len(s.calls) == 32


def test_fetch_product_none_when_sale_rate_zero_reached():
    s = FakeSession(synthetic(last_page=100, zero_at=22))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    assert m.fetch_product(s, "https://www.musinsa.com/products/999999", items) is None
    assert len(s.calls) == 22
    assert m.fetch_product(s, "https://www.musinsa.com/products/888888", items) is None
    assert len(s.calls) == 22


def test_fetch_product_none_at_end_of_list():
    s = FakeSession(synthetic(last_page=23))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    assert m.fetch_product(s, "https://www.musinsa.com/products/999999", items) is None
    assert len(s.calls) == 23


def test_fetch_product_cap_raises_fetch_error():
    s = FakeSession(synthetic(last_page=1000))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    with pytest.raises(FetchError, match="목록 상한 도달, 확인 불가"):
        m.fetch_product(s, "https://www.musinsa.com/products/999999", items)
    assert len(s.calls) == musinsa.DEEP_LOOKUP_MAX_PAGES == 150
    with pytest.raises(FetchError):
        m.fetch_product(s, "https://www.musinsa.com/products/999998", items)
    assert len(s.calls) == 150


def test_cap_not_error_if_list_ends_exactly_at_cap():
    s = FakeSession(synthetic(last_page=150))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    assert m.fetch_product(s, "https://www.musinsa.com/products/999999", items) is None


def test_deep_lookup_page_error_raises_fetch_error():
    ok = synthetic(last_page=100)
    s = FakeSession(lambda url: FakeResp({}, 500) if "page=22" in url else ok(url))
    m = musinsa.Musinsa()
    items = m.fetch_sale_items(s)
    with pytest.raises(FetchError):
        m.fetch_product(s, "https://www.musinsa.com/products/999999", items)


def test_state_resets_each_run():
    m = musinsa.Musinsa()
    s = FakeSession(synthetic(last_page=100))
    items = m.fetch_sale_items(s)
    m.fetch_product(s, "https://www.musinsa.com/products/2500", items)
    s2 = FakeSession(synthetic(last_page=3))
    items2 = m.fetch_sale_items(s2)
    assert m.fetch_product(s2, "https://www.musinsa.com/products/2500", items2) is None
