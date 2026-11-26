from __future__ import annotations

from tracker.models import PriceDrop, Product

FAILURE_ALERT_THRESHOLD = 3


def _base(entry: dict | None, url: str) -> dict:
    if entry is None:
        return {
            "url": url, "brand": None, "name": None, "image_url": None,
            "list_price": None, "price": None, "on_sale": False,
            "off_sale": False, "history": [], "last_error": None,
        }
    return {**entry, "history": [dict(h) for h in entry.get("history", [])]}


def record_price(
    entry: dict | None, product: Product, now: str
) -> tuple[dict, PriceDrop | None]:
    if product.price <= 0:
        raise ValueError(f"invalid price: {product.price}")
    old = _base(entry, product.url)
    prices = [h["price"] for h in old["history"]]
    previous = prices[-1] if prices else None
    was_off_sale = bool(old.get("off_sale"))

    drop: PriceDrop | None = None
    if was_off_sale and product.on_sale:
        kind = "sale_start"
        is_lowest = bool(prices) and product.price < min(prices)
    elif prices and product.price < previous:
        kind = "drop"
        is_lowest = product.price < min(prices)
    else:
        kind = None
        is_lowest = False
    if kind:
        drop = PriceDrop(
            key=f"{product.brand}:{product.product_id}", kind=kind,
            name=product.name, url=product.url, previous=previous,
            current=product.price, list_price=product.list_price,
            is_lowest=is_lowest,
        )

    history = old["history"]
    if previous is None or product.price != previous:
        history.append({"at": now, "price": product.price})
    new = {
        **old,
        "url": product.url, "brand": product.brand, "name": product.name,
        "image_url": product.image_url, "list_price": product.list_price,
        "price": product.price, "on_sale": product.on_sale,
        "off_sale": False, "history": history, "last_error": None,
    }
    return new, drop


def record_error(entry: dict | None, url: str, error: str) -> dict:
    return {**_base(entry, url), "last_error": error}


def record_off_sale(entry: dict | None, url: str) -> dict:
    return {
        **_base(entry, url),
        "off_sale": True, "on_sale": False, "last_error": None,
    }


def update_brand_status(
    status: dict | None, ok: bool, now: str
) -> tuple[dict, bool]:
    s = {"last_success": None, "consecutive_failures": 0, "alerted": False}
    if status:
        s.update(status)
    if ok:
        return {"last_success": now, "consecutive_failures": 0, "alerted": False}, False
    s["consecutive_failures"] += 1
    fire = s["consecutive_failures"] >= FAILURE_ALERT_THRESHOLD and not s["alerted"]
    if fire:
        s["alerted"] = True
    return s, fire
