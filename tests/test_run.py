import json

from tracker.http import FetchError
from tracker.models import Product
from tracker.notify import MailNotConfigured
from tracker.run import run

NOW1 = "2026-11-26T09:00:00+09:00"
NOW2 = "2026-11-26T15:00:00+09:00"


def prod(brand, pid, price, list_price=None, on_sale=True, image="img", name=None):
    return Product(brand, pid, name if name is not None else f"n{pid}",
                   f"https://{brand}.test/p/{pid}", image, list_price, price, on_sale)


class FakeBrand:
    """Simple brand: fetch_product looks the id up in `products`."""

    def __init__(self, name, sale=None, products=None, fail_sale=False):
        self.name = name
        self.sale = sale or []
        self.products = products or {}
        self.fail_sale = fail_sale
        self.calls = []

    def matches(self, url):
        return url.startswith(f"https://{self.name}.test/")

    def product_id(self, url):
        pid = url.rstrip("/").split("/")[-1].split("?")[0]
        if pid == "bad":
            raise ValueError("bad url")
        return pid

    def fetch_sale_items(self, session):
        self.calls.append("sale")
        if self.fail_sale:
            raise FetchError("down")
        return list(self.sale)

    def fetch_product(self, session, url, sale_items):
        self.calls.append("product")
        p = self.products[self.product_id(url)]
        if isinstance(p, Exception):
            raise p
        return p


class MusinsaLike(FakeBrand):
    """Only finds products via the sale list; None if absent; error if no list."""

    def fetch_product(self, session, url, sale_items):
        self.calls.append("product")
        if sale_items is None:
            raise FetchError("no sale list")
        pid = self.product_id(url)
        for p in sale_items:
            if p.product_id == pid:
                return p
        return None


class Sender:
    def __init__(self, exc=None):
        self.sent = []
        self.exc = exc

    def __call__(self, subject, body):
        if self.exc:
            raise self.exc
        self.sent.append((subject, body))


def setup(tmp_path, urls):
    (tmp_path / "watchlist.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")


def load(tmp_path, name):
    return json.loads((tmp_path / "data" / f"{name}.json").read_text(encoding="utf-8"))


def test_first_run_records_baseline_without_email(tmp_path):
    a = FakeBrand("a", sale=[prod("a", "1", 800, 1000)], products={"1": prod("a", "1", 800, 1000)})
    setup(tmp_path, ["https://a.test/p/1"])
    s = Sender()
    assert run(tmp_path, NOW1, [a], None, send=s) == 0
    assert s.sent == []
    w = load(tmp_path, "watch")["items"]["a:1"]
    assert w["price"] == 800 and len(w["history"]) == 1
    assert load(tmp_path, "sale_items")["updated_at"] == NOW1
    assert load(tmp_path, "status")["brands"]["a"]["consecutive_failures"] == 0
    assert (tmp_path / "data" / "watch.json").read_text(encoding="utf-8").endswith("}\n")


def test_drop_sends_one_email_for_all_drops(tmp_path):
    a = FakeBrand("a", products={"1": prod("a", "1", 800), "2": prod("a", "2", 500)})
    setup(tmp_path, ["https://a.test/p/1", "https://a.test/p/2"])
    s = Sender()
    run(tmp_path, NOW1, [a], None, send=s)
    a.products = {"1": prod("a", "1", 700), "2": prod("a", "2", 400)}
    assert run(tmp_path, NOW2, [a], None, send=s) == 0
    assert len(s.sent) == 1


def test_failed_brand_keeps_previous_sale_items(tmp_path):
    a = FakeBrand("a", sale=[prod("a", "1", 800, 1000)])
    b = FakeBrand("b", sale=[prod("b", "9", 90, 100)])
    setup(tmp_path, [])
    run(tmp_path, NOW1, [a, b], None, send=Sender())
    a.fail_sale = True
    b.sale = [prod("b", "8", 50, 100)]
    assert run(tmp_path, NOW2, [a, b], None, send=Sender()) == 0
    ids = {(i["brand"], i["product_id"]) for i in load(tmp_path, "sale_items")["items"]}
    assert ids == {("a", "1"), ("b", "8")}
    assert load(tmp_path, "status")["brands"]["a"]["consecutive_failures"] == 1


def test_unreadable_price_sets_error_no_email(tmp_path):
    a = FakeBrand("a", products={"1": prod("a", "1", 800)})
    setup(tmp_path, ["https://a.test/p/1"])
    s = Sender()
    run(tmp_path, NOW1, [a], None, send=s)
    a.products = {"1": prod("a", "1", 0)}
    assert run(tmp_path, NOW2, [a], None, send=s) == 0
    w = load(tmp_path, "watch")["items"]["a:1"]
    assert w["last_error"] == "가격을 읽을 수 없음"
    assert w["price"] == 800
    assert s.sent == []


def test_same_product_two_url_variants_is_one_entry(tmp_path):
    a = FakeBrand("a", products={"1": prod("a", "1", 800)})
    setup(tmp_path, ["https://a.test/p/1", "https://a.test/p/1?color=red"])
    run(tmp_path, NOW1, [a], None, send=Sender())
    items = load(tmp_path, "watch")["items"]
    assert list(items) == ["a:1"]
    assert a.calls.count("product") == 1


def test_unsupported_url_recorded_as_error(tmp_path):
    a = FakeBrand("a")
    setup(tmp_path, ["https://zzz.test/p/1", "https://a.test/p/bad"])
    assert run(tmp_path, NOW1, [a], None, send=Sender()) == 0
    items = load(tmp_path, "watch")["items"]
    assert items["url:https://zzz.test/p/1"]["last_error"] == "지원하지 않는 브랜드"
    assert items["url:https://a.test/p/bad"]["last_error"] == "상품 링크를 인식할 수 없음"


def test_removed_watchlist_url_dropped(tmp_path):
    a = FakeBrand("a", products={"1": prod("a", "1", 800), "2": prod("a", "2", 500)})
    setup(tmp_path, ["https://a.test/p/1", "https://a.test/p/2"])
    run(tmp_path, NOW1, [a], None, send=Sender())
    setup(tmp_path, ["https://a.test/p/1"])
    run(tmp_path, NOW2, [a], None, send=Sender())
    assert list(load(tmp_path, "watch")["items"]) == ["a:1"]


def test_send_failure_saves_data_and_returns_1(tmp_path):
    a = FakeBrand("a", products={"1": prod("a", "1", 800)})
    setup(tmp_path, ["https://a.test/p/1"])
    run(tmp_path, NOW1, [a], None, send=Sender())
    a.products = {"1": prod("a", "1", 700)}
    assert run(tmp_path, NOW2, [a], None, send=Sender(exc=RuntimeError("smtp"))) == 1
    assert load(tmp_path, "watch")["items"]["a:1"]["price"] == 700


def test_mail_not_configured_returns_0(tmp_path):
    a = FakeBrand("a", products={"1": prod("a", "1", 800)})
    setup(tmp_path, ["https://a.test/p/1"])
    run(tmp_path, NOW1, [a], None, send=Sender())
    a.products = {"1": prod("a", "1", 700)}
    assert run(tmp_path, NOW2, [a], None, send=Sender(exc=MailNotConfigured())) == 0


def test_third_consecutive_failure_sends_failure_email(tmp_path):
    a = FakeBrand("a", fail_sale=True)
    setup(tmp_path, [])
    s = Sender()
    for now in (NOW1, NOW2, "2026-11-26T21:00:00+09:00"):
        assert run(tmp_path, now, [a], None, send=s) == 0
    assert len(s.sent) == 1
    assert run(tmp_path, "2026-11-27T03:00:00+09:00", [a], None, send=s) == 0
    assert len(s.sent) == 1


def test_watched_item_absent_then_in_sale_list_sends_sale_start(tmp_path):
    m = MusinsaLike("m", sale=[])
    setup(tmp_path, ["https://m.test/p/1"])
    s = Sender()
    run(tmp_path, NOW1, [m], None, send=s)
    assert load(tmp_path, "watch")["items"]["m:1"]["off_sale"] is True
    m.sale = [prod("m", "1", 700, 1000)]
    run(tmp_path, NOW2, [m], None, send=s)
    assert len(s.sent) == 1
    assert m.calls[:2] == ["sale", "product"]


def test_sale_list_failure_does_not_mark_watched_off_sale(tmp_path):
    m = MusinsaLike("m", sale=[prod("m", "1", 700, 1000)])
    setup(tmp_path, ["https://m.test/p/1"])
    s = Sender()
    run(tmp_path, NOW1, [m], None, send=s)
    m.fail_sale = True
    run(tmp_path, NOW2, [m], None, send=s)
    w = load(tmp_path, "watch")["items"]["m:1"]
    assert w["off_sale"] is False
    assert w["last_error"]
    assert w["price"] == 700


def test_empty_image_filled_from_sale_list_or_existing(tmp_path):
    a = FakeBrand("a", sale=[prod("a", "1", 800, 1000, image="listimg")],
                  products={"1": prod("a", "1", 800, image="", name="")})
    setup(tmp_path, ["https://a.test/p/1"])
    run(tmp_path, NOW1, [a], None, send=Sender())
    w = load(tmp_path, "watch")["items"]["a:1"]
    assert w["image_url"] == "listimg"
    a.sale = []
    run(tmp_path, NOW2, [a], None, send=Sender())
    assert load(tmp_path, "watch")["items"]["a:1"]["image_url"] == "listimg"


def test_sale_items_deduped_and_sorted(tmp_path):
    a = FakeBrand("a", sale=[
        prod("a", "1", 900, None), prod("a", "2", 500, 1000),
        prod("a", "3", 800, 1000), prod("a", "2", 500, 1000),
    ])
    setup(tmp_path, [])
    run(tmp_path, NOW1, [a], None, send=Sender())
    ids = [i["product_id"] for i in load(tmp_path, "sale_items")["items"]]
    assert ids == ["2", "3", "1"]


def test_parser_value_error_is_not_mislabeled_as_price_error(tmp_path):
    a = FakeBrand("a", products={"1": ValueError("bad json")})
    setup(tmp_path, ["https://a.test/p/1"])
    assert run(tmp_path, NOW1, [a], None, send=Sender()) == 0
    err = load(tmp_path, "watch")["items"]["a:1"]["last_error"]
    assert err and err != "가격을 읽을 수 없음"


def test_unexpected_error_is_logged(tmp_path, capsys):
    a = FakeBrand("a", products={"1": KeyError("oops")})
    setup(tmp_path, ["https://a.test/p/1"])
    run(tmp_path, NOW1, [a], None, send=Sender())
    out = capsys.readouterr().out
    assert "a:1" in out and "KeyError" in out


def test_drop_mail_not_configured_still_attempts_failure_mail(tmp_path):
    a = FakeBrand("a", products={"1": prod("a", "1", 800)})
    setup(tmp_path, ["https://a.test/p/1"])
    run(tmp_path, NOW1, [a], None, send=Sender())
    a.fail_sale = True
    a.products = {"1": prod("a", "1", 700)}
    for now in (NOW2, "2026-11-26T21:00:00+09:00"):
        run(tmp_path, now, [a], None, send=Sender())
    attempts = []

    def send(subject, body):
        attempts.append(subject)
        raise MailNotConfigured()

    a.products = {"1": prod("a", "1", 600)}
    assert run(tmp_path, "2026-11-27T03:00:00+09:00", [a], None, send=send) == 0
    assert len(attempts) == 2