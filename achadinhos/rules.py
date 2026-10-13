"""Motor de regras: avalia ofertas contra as listas e calcula o score de "promoção real".

O score (0-100) prioriza o histórico de preço observado pelo próprio sistema e
desconfia do preço "de" informado pela loja (que pode ser maquiado).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PricePoint, Product, Watchlist
from .text import contains_term, normalize


@dataclass
class HistoryStats:
    points: int = 0
    days: float = 0.0
    median_90: float | None = None
    min_90: float | None = None
    max_90: float | None = None
    median_30: float | None = None

    @property
    def usable(self) -> bool:
        return self.points >= 2 and self.days >= 1


@dataclass
class Evaluation:
    score: float
    reasons: list[str] = field(default_factory=list)
    history: HistoryStats = field(default_factory=HistoryStats)


def history_stats(session: Session, fingerprint: str, before: datetime) -> HistoryStats:
    """Estatísticas de preço dos últimos 90 dias de todos os anúncios com o mesmo fingerprint."""
    since = before - timedelta(days=90)
    rows = session.execute(
        select(PricePoint.price, PricePoint.seen_at)
        .join(Product, Product.id == PricePoint.product_id)
        .where(Product.fingerprint == fingerprint)
        .where(PricePoint.seen_at >= since, PricePoint.seen_at < before)
    ).all()
    if not rows:
        return HistoryStats()
    prices = [r.price for r in rows]
    recent = [r.price for r in rows if r.seen_at >= before - timedelta(days=30)]
    oldest = min(r.seen_at for r in rows)
    return HistoryStats(
        points=len(rows),
        days=(before - oldest).total_seconds() / 86400,
        median_90=statistics.median(prices),
        min_90=min(prices),
        max_90=max(prices),
        median_30=statistics.median(recent) if recent else None,
    )


def evaluate(product: Product, stats: HistoryStats) -> Evaluation:
    score = 0.0
    reasons: list[str] = []
    price = product.price

    if product.discount_pct:
        score += min(product.discount_pct, 60) * 0.5
        reasons.append(f"{product.discount_pct:.0f}% off sobre o preço 'de' da loja")

    if stats.usable and stats.median_90:
        below = (stats.median_90 - price) / stats.median_90
        if below > 0:
            score += min(below * 100, 40)
            reasons.append(f"{below * 100:.0f}% abaixo da mediana de 90 dias (R$ {stats.median_90:.2f})")
        elif below < -0.02:
            score -= 15
            reasons.append(f"acima da mediana de 90 dias (R$ {stats.median_90:.2f})")
        if stats.min_90 is not None and price <= stats.min_90:
            score += 15
            reasons.append(f"menor preço em {min(stats.days, 90):.0f} dias")
        if product.old_price and stats.max_90 and product.old_price > stats.max_90 * 1.05:
            score -= 10
            reasons.append(
                f"preço 'de' (R$ {product.old_price:.2f}) maior que o máximo já visto "
                f"(R$ {stats.max_90:.2f}): desconto possivelmente inflado"
            )
        if stats.median_30 and stats.median_90 and stats.median_30 > stats.median_90 * 1.10:
            score -= 10
            reasons.append("preço subiu nos últimos 30 dias antes da oferta (suspeito)")
    else:
        reasons.append("histórico ainda curto: score baseado só no desconto informado")

    if product.popularity > 0:
        score += min(math.log10(1 + product.popularity) * 5, 10)
    if product.coupon:
        score += 5
        reasons.append(f"cupom: {product.coupon}")

    return Evaluation(score=round(max(0.0, min(100.0, score)), 1), reasons=reasons, history=stats)


def _norm_list(values) -> list[str]:
    return [v for v in (values or []) if isinstance(v, str) and v.strip()]


def match_watchlist(wl: Watchlist, product: Product, score: float | None = None) -> tuple[bool, list[str]]:
    """Retorna (casou?, motivos). Motivos explicam por que casou (ou o primeiro filtro que falhou)."""
    text = normalize(" ".join([product.title, product.keywords or "", product.category or ""]))
    toks = set(text.split())

    sources = _norm_list(wl.sources)
    if sources and product.source not in sources:
        return False, [f"fonte {product.source} fora da lista"]

    keywords = _norm_list(wl.keywords)
    hit = None
    if keywords:
        hit = next((k for k in keywords if contains_term(toks, text, k)), None)
        if not hit:
            return False, ["nenhuma palavra-chave encontrada"]

    for ex in _norm_list(wl.exclude_keywords):
        if contains_term(toks, text, ex):
            return False, [f"contém termo excluído '{ex}'"]

    stores = _norm_list(wl.stores)
    if stores:
        store = normalize(product.store)
        if not any(normalize(s) and normalize(s) in store for s in stores):
            return False, [f"loja '{product.store}' fora da lista"]

    categories = _norm_list(wl.categories)
    if categories:
        cat = normalize(product.category)
        if not any(normalize(c) and normalize(c) in cat for c in categories):
            return False, [f"categoria '{product.category}' fora da lista"]

    if wl.min_price is not None and product.price < wl.min_price:
        return False, ["abaixo do preço mínimo"]
    if wl.max_price is not None and product.price > wl.max_price:
        return False, ["acima do preço máximo"]
    if wl.min_discount is not None and (product.discount_pct or 0) < wl.min_discount:
        return False, ["desconto abaixo do mínimo"]
    if wl.require_coupon and not product.coupon:
        return False, ["sem cupom"]
    if wl.min_score is not None and (score or 0) < wl.min_score:
        return False, [f"score {score or 0:.0f} abaixo do mínimo {wl.min_score:.0f}"]

    return True, [f"palavra-chave: {hit}"] if hit else ["casou com os filtros da lista"]
