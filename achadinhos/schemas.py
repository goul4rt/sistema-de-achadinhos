"""Validação de entrada da API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _clean_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace("\n", ",").split(",")
    return [str(v).strip() for v in value if str(v).strip()]


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    niche: str = ""
    description: str = ""
    active: bool = True
    keywords: list[str] = []
    exclude_keywords: list[str] = []
    stores: list[str] = []
    categories: list[str] = []
    sources: list[str] = []
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    min_discount: float | None = Field(default=None, ge=0, le=100)
    min_score: float | None = Field(default=None, ge=0, le=100)
    require_coupon: bool = False
    webhook_url: str = ""

    @field_validator("keywords", "exclude_keywords", "stores", "categories", "sources", mode="before")
    @classmethod
    def _lists(cls, v):
        return _clean_list(v)

    @field_validator("webhook_url")
    @classmethod
    def _webhook(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("webhook_url precisa começar com http:// ou https://")
        return v
