"""API JSON. É a porta de integração da fase 2 (disparo para grupos/canais)."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from . import __version__
from .collector import run_collection
from .db import get_db
from .models import CollectionRun, Match, PricePoint, Product, Watchlist
from .pipeline import backfill_watchlist, preview_watchlist
from .scheduler import next_run
from .schemas import WatchlistIn
from .serializers import match_to_dict, product_to_dict, run_to_dict, watchlist_to_dict
from .sources import get_sources

router = APIRouter(prefix="/api")


@router.get("/health")
def health(db: Session = Depends(get_db)):
    return {
        "status": "ok",
        "version": __version__,
        "products": db.scalar(select(func.count(Product.id))),
        "watchlists": db.scalar(select(func.count(Watchlist.id))),
        "matches": db.scalar(select(func.count(Match.id))),
        "next_collection": next_run().isoformat() if next_run() else None,
        "sources": [
            {"name": s.name, "label": s.label, "status": s.status(), "feed": s.supports_feed, "search": s.supports_search}
            for s in get_sources()
        ],
    }


# ---- listas -------------------------------------------------------------------

def _get_wl(db: Session, wl_id: int) -> Watchlist:
    wl = db.get(Watchlist, wl_id)
    if not wl:
        raise HTTPException(404, "lista não encontrada")
    return wl


@router.get("/watchlists")
def list_watchlists(db: Session = Depends(get_db)):
    rows = db.execute(select(Watchlist).order_by(Watchlist.name)).scalars()
    return [watchlist_to_dict(w) for w in rows]


@router.post("/watchlists", status_code=201)
def create_watchlist(data: WatchlistIn, backfill_hours: int = 48, db: Session = Depends(get_db)):
    wl = Watchlist(**data.model_dump())
    db.add(wl)
    db.flush()
    created = backfill_watchlist(db, wl, backfill_hours) if backfill_hours > 0 and wl.active else []
    db.commit()
    return {**watchlist_to_dict(wl), "backfilled_matches": len(created)}


@router.get("/watchlists/{wl_id}")
def get_watchlist(wl_id: int, db: Session = Depends(get_db)):
    return watchlist_to_dict(_get_wl(db, wl_id))


@router.put("/watchlists/{wl_id}")
def update_watchlist(wl_id: int, data: WatchlistIn, db: Session = Depends(get_db)):
    wl = _get_wl(db, wl_id)
    for k, v in data.model_dump().items():
        setattr(wl, k, v)
    db.commit()
    return watchlist_to_dict(wl)


@router.delete("/watchlists/{wl_id}", status_code=204)
def delete_watchlist(wl_id: int, db: Session = Depends(get_db)):
    db.delete(_get_wl(db, wl_id))
    db.commit()


@router.post("/watchlists/preview")
def preview(data: WatchlistIn, hours: int = 72, limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    """Testa critérios sem salvar: o que essa lista teria pego nas últimas `hours` horas."""
    wl = Watchlist(**data.model_dump())
    return [
        {"product": product_to_dict(p), "score": ev.score, "reasons": ev.reasons}
        for p, ev in preview_watchlist(db, wl, hours, limit)
    ]


# ---- matches (caixa de saída para a fase 2) ----------------------------------

def _matches_query(db: Session, after_id: int, limit: int, wl_id: int | None, min_score: float | None):
    q = (
        select(Match)
        .options(joinedload(Match.product), joinedload(Match.watchlist))
        .where(Match.id > after_id)
        .order_by(Match.id)
        .limit(limit)
    )
    if wl_id is not None:
        q = q.where(Match.watchlist_id == wl_id)
    if min_score is not None:
        q = q.where(Match.score >= min_score)
    return [match_to_dict(m) for m in db.execute(q).unique().scalars()]


@router.get("/matches")
def list_matches(
    after_id: int = 0,
    limit: int = Query(100, le=500),
    watchlist_id: int | None = None,
    min_score: float | None = None,
    db: Session = Depends(get_db),
):
    """Feed incremental: guarde o maior `id` recebido e passe como `after_id` na próxima chamada."""
    return _matches_query(db, after_id, limit, watchlist_id, min_score)


@router.get("/watchlists/{wl_id}/matches")
def watchlist_matches(wl_id: int, after_id: int = 0, limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    _get_wl(db, wl_id)
    return _matches_query(db, after_id, limit, wl_id, None)


# ---- ofertas e histórico -------------------------------------------------------

@router.get("/offers")
def list_offers(
    q: str = "",
    store: str = "",
    source: str = "",
    limit: int = Query(50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = select(Product).order_by(Product.last_seen.desc(), Product.id.desc())
    if q:
        for word in q.split():
            query = query.where(Product.title.ilike(f"%{word}%"))
    if store:
        query = query.where(Product.store.ilike(f"%{store}%"))
    if source:
        query = query.where(Product.source == source)
    return [product_to_dict(p) for p in db.execute(query.offset(offset).limit(limit)).scalars()]


@router.get("/offers/{product_id}/history")
def offer_history(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "oferta não encontrada")
    rows = db.execute(
        select(PricePoint, Product.source, Product.external_id)
        .join(Product, Product.id == PricePoint.product_id)
        .where(or_(Product.id == product_id, Product.fingerprint == product.fingerprint))
        .order_by(PricePoint.seen_at)
    ).all()
    return {
        "product": product_to_dict(product),
        "history": [
            {"price": pp.price, "old_price": pp.old_price, "seen_at": pp.seen_at.isoformat() + "Z", "source": src, "external_id": ext}
            for pp, src, ext in rows
        ],
    }


# ---- coleta --------------------------------------------------------------------

@router.post("/collect", status_code=202)
def collect_now(source: str | None = None, wait: bool = False):
    only = [source] if source else None
    if wait:
        summary = run_collection(only)
        return {"skipped": summary.skipped, "runs": summary.runs}
    threading.Thread(target=run_collection, args=(only,), daemon=True).start()
    return {"status": "coleta iniciada"}


@router.get("/runs")
def list_runs(limit: int = Query(30, le=200), db: Session = Depends(get_db)):
    rows = db.execute(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(limit)).scalars()
    return [run_to_dict(r) for r in rows]
