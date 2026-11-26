from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Product:
    brand: str
    product_id: str
    name: str
    url: str
    image_url: str
    list_price: int | None
    price: int
    on_sale: bool

    @property
    def discount_rate(self) -> int | None:
        if self.list_price is None or self.list_price <= self.price:
            return None
        return round((self.list_price - self.price) / self.list_price * 100)

    def to_dict(self) -> dict:
        return {**asdict(self), "discount_rate": self.discount_rate}


@dataclass(frozen=True)
class PriceDrop:
    key: str
    kind: str  # "drop" or "sale_start"
    name: str
    url: str
    previous: int | None
    current: int
    list_price: int | None
    is_lowest: bool
