"""Ingestão: RawOffer -> Product + histórico de preço -> avaliação contra as listas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Match, PricePoint, Product, Watchlist, utcnow
from .rules import Evaluation, evaluate, history_stats, match_watchlist
from .serializers import match_to_dict
from .sources.base import RawOffer
from .text import fingerprint

log = logging.getLogger(__name__)

# Nova oferta do mesmo produto só gera novo match se o preço cair pelo menos isso.
REMATCH_PRICE_DROP = 0.05
# Repostagens do mesmo produto (mesmo fingerprint) dentro dessa janela são deduplicadas.
DEDUP_WINDOW = timedelta(days=7)
# Novo ponto de preço é gravado se o preço mudou ou se o último ponto é mais velho que isso.
PRICE_POINT_REFRESH = timedelta(hours=12)


@dataclass
class IngestResult:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    new_matches: list[Match] = field(default_factory=list)


def upsert_product(session: Session, raw: RawOffer, now: datetime) -> tuple[Product, bool, bool]:
    """Cria/atualiza o produto. Retorna (produto, criado?, preço mudou?)."""
    product = session.execute(
        select(Product).where(Product.source == raw.source, Product.external_id == raw.external_id)
    ).scalar_one_or_none()
    created = product is None
    if created:
        product = Product(source=raw.source, external_id=raw.external_id, first_seen=now)
        session.add(product)
    changed = created or product.price != raw.price
    product.title = raw.title
    product.url = raw.url
    product.image_url = raw.image_url
    product.store = raw.store
    product.category = raw.category
    product.keywords = raw.keywords
    product.fingerprint = fingerprint(raw.title, raw.store)
    product.price = raw.price
    product.old_price = raw.old_price
    product.discount_pct = raw.discount_pct
    product.coupon = raw.coupon
    product.affiliate_url = raw.affiliate_url
    product.popularity = raw.popularity
    product.published_at = raw.published_at
    product.extra = raw.extra
    product.last_seen = now
    session.flush()
    return product, created, changed


def _maybe_add_price_point(session: Session, product: Product, now: datetime) -> None:
    last = session.execute(
        select(PricePoint)
        .where(PricePoint.product_id == product.id)
        .order_by(PricePoint.seen_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last is None or last.price != product.price or now - last.seen_at >= PRICE_POINT_REFRESH:
        session.add(
            PricePoint(product_id=product.id, price=product.price, old_price=product.old_price, seen_at=now)
        )


def is_duplicate(session: Session, wl: Watchlist, product: Product, now: datetime) -> bool:
    last = session.execute(
        select(Match)
        .join(Product, Product.id == Match.product_id)
        .where(Match.watchlist_id == wl.id)
        .where(
            or_(
                Match.product_id == product.id,
                (Product.fingerprint == product.fingerprint) & (Match.created_at >= now - DEDUP_WINDOW),
            )
        )
        .order_by(Match.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return last is not None and product.price > last.price * (1 - REMATCH_PRICE_DROP)


def evaluate_against_lists(
    session: Session,
    product: Product,
    ev: Evaluation,
    watchlists: list[Watchlist],
    now: datetime,
) -> list[Match]:
    created = []
    for wl in watchlists:
        ok, reasons = match_watchlist(wl, product, ev.score)
        if not ok or is_duplicate(session, wl, product, now):
            continue
        m = Match(
            watchlist_id=wl.id,
            product_id=product.id,
            price=product.price,
            score=ev.score,
            reasons=reasons + ev.reasons,
            created_at=now,
        )
        session.add(m)
        session.flush()
        created.append(m)
    return created


def active_watchlists(session: Session) -> list[Watchlist]:
    return list(session.execute(select(Watchlist).where(Watchlist.active.is_(True))).scalars())


def ingest(session: Session, raws: list[RawOffer], now: datetime | None = None) -> IngestResult:
    now = now or utcnow()
    result = IngestResult(fetched=len(raws))
    watchlists = active_watchlists(session)
    seen: set[tuple[str, str]] = set()
    for raw in raws:
        key = (raw.source, raw.external_id)
        if key in seen or not raw.title:
            continue
        seen.add(key)
        product, created, changed = upsert_product(session, raw, now)
        if created:
            result.created += 1
        elif changed:
            result.updated += 1
        if created or changed:
            # Score calculado com o histórico ANTERIOR a esta observação.
            ev = evaluate(product, history_stats(session, product.fingerprint, now))
            _maybe_add_price_point(session, product, now)
            result.new_matches += evaluate_against_lists(session, product, ev, watchlists, now)
        else:
            _maybe_add_price_point(session, product, now)
    session.flush()
    return result


def _latest_point_time(session: Session, product: Product) -> datetime:
    t = session.execute(
        select(PricePoint.seen_at)
        .where(PricePoint.product_id == product.id)
        .order_by(PricePoint.seen_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return t or product.last_seen


def recent_products(session: Session, hours: int) -> list[Product]:
    since = utcnow() - timedelta(hours=hours)
    return list(
        session.execute(
            select(Product).where(Product.last_seen >= since).order_by(Product.last_seen.desc())
        ).scalars()
    )


def preview_watchlist(session: Session, wl: Watchlist, hours: int = 72, limit: int = 100) -> list[tuple[Product, Evaluation]]:
    """Testa uma lista (salva ou não) contra as ofertas recentes, sem gravar nada."""
    out = []
    for product in recent_products(session, hours):
        ev = evaluate(product, history_stats(session, product.fingerprint, _latest_point_time(session, product)))
        ok, reasons = match_watchlist(wl, product, ev.score)
        if ok:
            ev.reasons = reasons + ev.reasons
            out.append((product, ev))
            if len(out) >= limit:
                break
    return out


def backfill_watchlist(session: Session, wl: Watchlist, hours: int = 48) -> list[Match]:
    """Ao criar/editar uma lista, aplica nas ofertas das últimas horas."""
    now = utcnow()
    created = []
    for product in recent_products(session, hours):
        ev = evaluate(product, history_stats(session, product.fingerprint, _latest_point_time(session, product)))
        created += evaluate_against_lists(session, product, ev, [wl], now)
    return created


def deliver_webhooks(session: Session, matches: list[Match], client: httpx.Client | None = None) -> None:
    """POST do match em JSON para o webhook da lista (melhor esforço, não bloqueia a coleta)."""
    pending = [m for m in matches if m.watchlist and m.watchlist.webhook_url]
    if not pending:
        return
    own_client = client is None
    client = client or httpx.Client(timeout=10)
    try:
        for m in pending:
            try:
                resp = client.post(m.watchlist.webhook_url, json={"event": "match.created", "match": match_to_dict(m)})
                m.webhook_status = f"http {resp.status_code}"
            except httpx.HTTPError as exc:
                m.webhook_status = f"erro: {type(exc).__name__}"
                log.warning("webhook falhou para lista %s: %s", m.watchlist_id, exc)
    finally:
        if own_client:
            client.close()
