from __future__ import annotations

import dataclasses
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tracker.brands import BRANDS
from tracker.history import (
    record_error,
    record_off_sale,
    record_price,
    update_brand_status,
)
from tracker.http import FetchError, make_session
from tracker.models import PriceDrop, Product
from tracker.notify import (
    MailNotConfigured,
    build_drop_email,
    build_failure_email,
    send_email,
)
from tracker.watchlist import parse_watchlist


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sort_key(item: dict) -> tuple:
    rate = item.get("discount_rate")
    return (rate is None, -(rate or 0), item["price"])


def _fill_brand(entry: dict, brand_name: str | None) -> dict:
    if brand_name and not entry.get("brand"):
        entry = {**entry, "brand": brand_name}
    return entry


def _complete(product: Product, existing: dict | None, sale: list[Product] | None) -> Product:
    """Fill empty image_url / name from the existing entry or this run's sale list."""
    image, name = product.image_url, product.name
    listed = next(
        (p for p in (sale or []) if p.product_id == product.product_id), None
    )
    if not image:
        image = (existing or {}).get("image_url") or (listed.image_url if listed else "")
    if not name:
        name = (existing or {}).get("name") or (listed.name if listed else "")
    if image == product.image_url and name == product.name:
        return product
    return dataclasses.replace(product, image_url=image, name=name)


def run(root: Path, now: str, brands: list, session, send=send_email) -> int:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    old_sale = _read_json(data_dir / "sale_items.json", {"items": []})["items"]
    old_watch = _read_json(data_dir / "watch.json", {"items": {}})["items"]
    status = _read_json(data_dir / "status.json", {"brands": {}})["brands"]

    # 1. sale lists (always before any fetch_product of the same brand)
    sale_by_brand: dict[str, list[Product] | None] = {}
    new_sale: list[dict] = []
    failed_brands: list[str] = []
    new_status: dict[str, dict] = {}
    for brand in brands:
        try:
            items = brand.fetch_sale_items(session)
        except Exception as e:  # FetchError or a parser bug: keep going
            print(f"[{brand.name}] sale list failed: {e}")
            items = None
        sale_by_brand[brand.name] = items
        if items is None:
            new_sale.extend(i for i in old_sale if i.get("brand") == brand.name)
        else:
            deduped = {p.product_id: p for p in items}
            new_sale.extend(p.to_dict() for p in deduped.values())
        new_status[brand.name], alert = update_brand_status(
            status.get(brand.name), items is not None, now
        )
        if alert:
            failed_brands.append(brand.name)

    # 2. watchlist
    text = (root / "watchlist.txt").read_text(encoding="utf-8") if (
        root / "watchlist.txt"
    ).exists() else ""
    new_watch: dict[str, dict] = {}
    drops: list[PriceDrop] = []
    for url in parse_watchlist(text):
        brand = next((b for b in brands if b.matches(url)), None)
        key = f"url:{url}"
        err = "지원하지 않는 브랜드"
        if brand is not None:
            try:
                key = f"{brand.name}:{brand.product_id(url)}"
                err = None
            except ValueError:
                err = "상품 링크를 인식할 수 없음"
        if key in new_watch:
            continue
        existing = old_watch.get(key)
        bname = brand.name if brand else None
        if err is not None:
            new_watch[key] = _fill_brand(record_error(existing, url, err), bname)
            continue
        sale = sale_by_brand.get(brand.name)
        try:
            product = brand.fetch_product(session, url, sale)
            if product is None:
                new_watch[key] = _fill_brand(record_off_sale(existing, url), bname)
                continue
            product = _complete(product, existing, sale)
        except Exception as e:  # FetchError and unexpected parser errors
            if isinstance(e, FetchError):
                msg = str(e)
            else:
                msg = f"예기치 않은 오류: {type(e).__name__}"
                print(f"[{brand.name}] unexpected error for {key}: "
                      f"{type(e).__name__}: {e}")
                traceback.print_exc()
            new_watch[key] = _fill_brand(record_error(existing, url, msg), bname)
            continue
        try:
            entry, drop = record_price(existing, product, now)
        except ValueError:
            new_watch[key] = _fill_brand(
                record_error(existing, url, "가격을 읽을 수 없음"), bname
            )
            continue
        new_watch[key] = entry
        if drop:
            drops.append(drop)

    # 3. save before sending anything
    new_sale.sort(key=_sort_key)
    _write_json(data_dir / "sale_items.json", {"updated_at": now, "items": new_sale})
    _write_json(data_dir / "watch.json", {"items": new_watch})
    _write_json(data_dir / "status.json", {"brands": new_status})

    # 4. notify
    code = 0
    mails = []
    if drops:
        mails.append(build_drop_email(drops))
    if failed_brands:
        mails.append(build_failure_email(failed_brands))
    for subject, body in mails:
        try:
            send(subject, body)
        except MailNotConfigured:
            print("warning: mail is not configured; skipping notification")
        except Exception as e:
            print(f"error: failed to send email: {type(e).__name__}")
            code = 1
    print(
        "summary: "
        + ", ".join(
            f"{b.name}={sum(1 for i in new_sale if i['brand'] == b.name)}" for b in brands
        )
        + f", watched={len(new_watch)}, drops={len(drops)}"
    )
    return code


def main() -> None:
    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    root = Path(__file__).resolve().parents[1]
    sys.exit(run(root, now, BRANDS, make_session()))


if __name__ == "__main__":
    main()
