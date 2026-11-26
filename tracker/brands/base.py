from __future__ import annotations

from typing import Protocol

from requests import Session

from tracker.http import FetchError
from tracker.models import Product

__all__ = ["Brand", "FetchError"]


class Brand(Protocol):
    name: str

    def matches(self, url: str) -> bool: ...

    def product_id(self, url: str) -> str: ...

    def fetch_sale_items(self, session: Session) -> list[Product]: ...

    def fetch_product(
        self, session: Session, url: str, sale_items: list[Product] | None
    ) -> Product | None:
        """None = not on sale, price unknown (Musinsa only). Failures raise FetchError."""
        ...
