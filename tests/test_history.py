import pytest

from tracker.history import (
    record_price, record_error, record_off_sale, update_brand_status,
)
from tracker.models import Product


def P(**kw):
    base = dict(brand="uniqlo", product_id="1", name="n", url="u", image_url="i",
                list_price=None, price=19900, on_sale=False)
    base.update(kw)
    return Product(**base)


def test_first_record_is_baseline_no_drop():
    e, d = record_price(None, P(price=19900), "t1")
    assert d is None and e["history"] == [{"at": "t1", "price": 19900}]


def test_same_price_not_appended_no_drop():
    e, _ = record_price(None, P(price=19900), "t1")
    e, d = record_price(e, P(price=19900), "t2")
    assert d is None and len(e["history"]) == 1


def test_drop_detected_and_lowest():
    e, _ = record_price(None, P(price=19900), "t1")
    e, d = record_price(e, P(price=14900), "t2")
    assert d.previous == 19900 and d.current == 14900 and d.is_lowest
    assert d.kind == "drop" and d.key == "uniqlo:1"


def test_drop_after_rise_not_lowest():
    e, _ = record_price(None, P(price=14900), "t1")
    e, _ = record_price(e, P(price=19900), "t2")
    e, d = record_price(e, P(price=16900), "t3")
    assert d.previous == 19900 and not d.is_lowest


def test_off_sale_then_on_sale_is_sale_start():
    e = record_off_sale(None, "u")
    e, d = record_price(e, P(price=29900, on_sale=True), "t1")
    assert d.kind == "sale_start" and d.previous is None and e["off_sale"] is False
    assert not d.is_lowest


def test_off_sale_then_seen_not_on_sale_no_alert():
    e = record_off_sale(None, "u")
    e, d = record_price(e, P(price=29900, on_sale=False), "t1")
    assert d is None


def test_sale_start_with_history_lowest_and_previous():
    e, _ = record_price(None, P(price=29900), "t1")
    e = record_off_sale(e, "u")
    assert e["off_sale"] is True and e["on_sale"] is False and len(e["history"]) == 1
    e, d = record_price(e, P(price=19900, on_sale=True), "t2")
    assert d.kind == "sale_start" and d.previous == 29900 and d.is_lowest


def test_success_clears_last_error():
    e = record_error(None, "u", "boom")
    e, _ = record_price(e, P(), "t")
    assert e["last_error"] is None


def test_record_error_keeps_history_and_does_not_mutate():
    e, _ = record_price(None, P(), "t1")
    e2 = record_error(e, "u", "boom")
    assert e2["history"] == e["history"] and e2["last_error"] == "boom"
    assert e["last_error"] is None


def test_record_off_sale_clears_error():
    e = record_error(None, "u", "boom")
    e = record_off_sale(e, "u")
    assert e["last_error"] is None and e["off_sale"] is True


def test_invalid_price_raises():
    with pytest.raises(ValueError):
        record_price(None, P(price=0), "t")


def test_failure_alert_fires_once_at_third_then_resets():
    s = None
    fired = []
    for ok in [False, False, False, False, True, False, False, False]:
        s, f = update_brand_status(s, ok, "t")
        fired.append(f)
    assert fired == [False, False, True, False, False, False, False, True]


def test_status_success_sets_last_success():
    s, f = update_brand_status(None, True, "t9")
    assert s == {"last_success": "t9", "consecutive_failures": 0, "alerted": False}
