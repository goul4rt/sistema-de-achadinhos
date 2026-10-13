"""Conversão de modelos para dicionários (JSON da API e payload de webhook)."""

from __future__ import annotations

from datetime import datetime

from .models import CollectionRun, Match, Product, Watchlist


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def product_to_dict(p: Product) -> dict:
    return {
        "id": p.id,
        "source": p.source,
        "external_id": p.external_id,
        "title": p.title,
        "price": p.price,
        "old_price": p.old_price,
        "discount_pct": p.discount_pct,
        "coupon": p.coupon,
        "store": p.store,
        "category": p.category,
        "url": p.url,
        "affiliate_url": p.affiliate_url,
        "image_url": p.image_url,
        "popularity": p.popularity,
        "fingerprint": p.fingerprint,
        "published_at": _dt(p.published_at),
        "first_seen": _dt(p.first_seen),
        "last_seen": _dt(p.last_seen),
        "extra": p.extra or {},
    }


def watchlist_to_dict(w: Watchlist) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "niche": w.niche,
        "description": w.description,
        "active": w.active,
        "keywords": w.keywords or [],
        "exclude_keywords": w.exclude_keywords or [],
        "stores": w.stores or [],
        "categories": w.categories or [],
        "sources": w.sources or [],
        "min_price": w.min_price,
        "max_price": w.max_price,
        "min_discount": w.min_discount,
        "min_score": w.min_score,
        "require_coupon": w.require_coupon,
        "webhook_url": w.webhook_url,
        "created_at": _dt(w.created_at),
        "updated_at": _dt(w.updated_at),
    }


def match_to_dict(m: Match) -> dict:
    wl = m.watchlist
    return {
        "id": m.id,
        "watchlist_id": m.watchlist_id,
        "watchlist_name": wl.name if wl else None,
        "niche": wl.niche if wl else None,
        "price": m.price,
        "score": m.score,
        "reasons": m.reasons or [],
        "created_at": _dt(m.created_at),
        "webhook_status": m.webhook_status,
        "product": product_to_dict(m.product) if m.product else None,
    }


def run_to_dict(r: CollectionRun) -> dict:
    return {
        "id": r.id,
        "source": r.source,
        "query": r.query,
        "started_at": _dt(r.started_at),
        "finished_at": _dt(r.finished_at),
        "fetched": r.fetched,
        "created": r.created,
        "updated": r.updated,
        "matches": r.matches,
        "error": r.error,
    }
