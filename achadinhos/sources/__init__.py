"""Registro das fontes. Para adicionar uma loja nova, crie um Source e registre aqui."""

from __future__ import annotations

from .aliexpress import AliExpressSource
from .base import RawOffer, Source, SourceError
from .promobit import PromobitSource
from .shopee import ShopeeSource

ALL_SOURCES: list[Source] = [PromobitSource(), ShopeeSource(), AliExpressSource()]


def get_sources() -> list[Source]:
    return list(ALL_SOURCES)


def get_source(name: str) -> Source | None:
    return next((s for s in ALL_SOURCES if s.name == name), None)


__all__ = ["RawOffer", "Source", "SourceError", "get_sources", "get_source", "ALL_SOURCES"]
