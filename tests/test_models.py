from tracker.models import Product


def test_discount_rate():
    p = Product("spao", "E1", "n", "u", "i", list_price=19900, price=14900, on_sale=True)
    assert p.discount_rate == 25


def test_discount_rate_none_without_list_price():
    assert Product("uniqlo", "E1", "n", "u", "i", None, 19900, True).discount_rate is None
    assert Product("spao", "E1", "n", "u", "i", 19900, 19900, False).discount_rate is None


def test_to_dict_is_json_serializable_and_includes_discount_rate():
    import json

    p = Product("spao", "E1", "n", "u", "i", list_price=19900, price=14900, on_sale=True)
    d = p.to_dict()
    assert d == {
        "brand": "spao",
        "product_id": "E1",
        "name": "n",
        "url": "u",
        "image_url": "i",
        "list_price": 19900,
        "price": 14900,
        "on_sale": True,
        "discount_rate": 25,
    }
    assert json.loads(json.dumps(d)) == d
