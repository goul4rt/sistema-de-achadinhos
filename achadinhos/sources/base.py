"""Interface comum das fontes de ofertas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import httpx


@dataclass
class RawOffer:
    source: str
    external_id: str
    title: str
    price: float
    url: str = ""
    old_price: float | None = None
    image_url: str = ""
    store: str = ""
    category: str = ""
    keywords: str = ""
    coupon: str = ""
    affiliate_url: str = ""
    popularity: int = 0
    published_at: datetime | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # "De" riscado só vale se for maior que o preço atual.
        if self.old_price is not None and self.old_price <= self.price:
            self.old_price = None

    @property
    def discount_pct(self) -> float | None:
        if self.old_price and self.old_price > 0:
            return round((1 - self.price / self.old_price) * 100, 1)
        return None


class SourceError(RuntimeError):
    pass


class Source:
    """Uma fonte implementa fetch_latest() (feed) e/ou search(query) (busca ativa)."""

    name: str = "base"
    label: str = "Base"
    supports_feed: bool = False
    supports_search: bool = False

    def enabled(self) -> bool:
        return True

    def status(self) -> str:
        return "ativa" if self.enabled() else "desativada"

    def fetch_latest(self, client: httpx.Client) -> list[RawOffer]:
        raise NotImplementedError

    def search(self, query: str, client: httpx.Client) -> list[RawOffer]:
        raise NotImplementedError


def to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None
