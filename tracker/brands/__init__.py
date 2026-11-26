from __future__ import annotations

from tracker.brands.base import Brand
from tracker.brands.uniqlo import UNIQLO

# Later brand modules (musinsa, spao) append themselves here.
BRANDS: list[Brand] = [UNIQLO]


def brand_for_url(url: str) -> Brand | None:
    for b in BRANDS:
        if b.matches(url):
            return b
    return None
