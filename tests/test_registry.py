from tracker.brands import BRANDS, brand_for_url


def test_brand_for_url():
    assert brand_for_url("https://www.uniqlo.com/kr/ko/products/E486821-000/00").name == "uniqlo"
    assert brand_for_url("https://example.com/x") is None


def test_registry_contains_uniqlo():
    assert "uniqlo" in [b.name for b in BRANDS]
