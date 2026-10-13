"""Painel web simples (HTML renderizado no servidor) para gerenciar listas e ver ofertas."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .collector import run_collection
from .db import get_db
from .models import CollectionRun, Match, PricePoint, Product, Watchlist
from .pipeline import backfill_watchlist, preview_watchlist
from .scheduler import next_run
from .schemas import WatchlistIn
from .sources import get_sources

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def brl(value) -> str:
    if value is None:
        return "-"
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


templates.env.filters["brl"] = brl
templates.env.filters["join_list"] = lambda v: ", ".join(v or [])


def _form_to_data(form) -> dict:
    def num(key):
        v = (form.get(key) or "").strip().replace(",", ".")
        return float(v) if v else None

    return {
        "name": form.get("name", "").strip(),
        "niche": form.get("niche", "").strip(),
        "description": form.get("description", "").strip(),
        "active": form.get("active") == "on",
        "keywords": form.get("keywords", ""),
        "exclude_keywords": form.get("exclude_keywords", ""),
        "stores": form.get("stores", ""),
        "categories": form.get("categories", ""),
        "sources": form.getlist("sources"),
        "min_price": num("min_price"),
        "max_price": num("max_price"),
        "min_discount": num("min_discount"),
        "min_score": num("min_score"),
        "require_coupon": form.get("require_coupon") == "on",
        "webhook_url": form.get("webhook_url", "").strip(),
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = select(Product).order_by(Product.last_seen.desc(), Product.id.desc()).limit(80)
    if q:
        for word in q.split():
            query = query.where(or_(Product.title.ilike(f"%{word}%"), Product.store.ilike(f"%{word}%")))
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "offers": db.execute(query).scalars().all(),
            "q": q,
            "runs": db.execute(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(8)).scalars().all(),
            "sources": get_sources(),
            "counts": {
                "products": db.scalar(select(func.count(Product.id))),
                "prices": db.scalar(select(func.count(PricePoint.id))),
                "lists": db.scalar(select(func.count(Watchlist.id))),
                "matches": db.scalar(select(func.count(Match.id))),
            },
            "next_run": next_run(),
        },
    )


@router.post("/coletar")
def collect(request: Request):
    threading.Thread(target=run_collection, daemon=True).start()
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


@router.get("/listas", response_class=HTMLResponse)
def lists(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        select(Watchlist, func.count(Match.id))
        .outerjoin(Match, Match.watchlist_id == Watchlist.id)
        .group_by(Watchlist.id)
        .order_by(Watchlist.name)
    ).all()
    return templates.TemplateResponse(
        request, "lists.html", {"rows": rows, "wl": None, "sources": get_sources(), "errors": []}
    )


def _render_form(request, wl, errors, db, status=400):
    tpl = "list_detail.html" if wl and wl.id else "lists.html"
    ctx = {"wl": wl, "sources": get_sources(), "errors": errors, "matches": [], "preview": None, "rows": []}
    return templates.TemplateResponse(request, tpl, ctx, status_code=status)


@router.post("/listas")
async def create_list(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        data = WatchlistIn(**_form_to_data(form))
    except (ValidationError, ValueError) as exc:
        return _render_form(request, None, [str(exc)], db)
    wl = Watchlist(**data.model_dump())
    db.add(wl)
    db.flush()
    if wl.active:
        backfill_watchlist(db, wl, 48)
    db.commit()
    return RedirectResponse(f"/listas/{wl.id}", status_code=303)


@router.get("/listas/{wl_id}", response_class=HTMLResponse)
def list_detail(request: Request, wl_id: int, preview: bool = False, db: Session = Depends(get_db)):
    wl = db.get(Watchlist, wl_id)
    if not wl:
        raise HTTPException(404)
    matches = (
        db.execute(
            select(Match)
            .options(joinedload(Match.product))
            .where(Match.watchlist_id == wl_id)
            .order_by(Match.id.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "list_detail.html",
        {
            "wl": wl,
            "matches": matches,
            "sources": get_sources(),
            "errors": [],
            "preview": preview_watchlist(db, wl, 72, 50) if preview else None,
        },
    )


@router.post("/listas/{wl_id}")
async def update_list(request: Request, wl_id: int, db: Session = Depends(get_db)):
    wl = db.get(Watchlist, wl_id)
    if not wl:
        raise HTTPException(404)
    form = await request.form()
    if form.get("_action") == "delete":
        db.delete(wl)
        db.commit()
        return RedirectResponse("/listas", status_code=303)
    try:
        data = WatchlistIn(**_form_to_data(form))
    except (ValidationError, ValueError) as exc:
        return _render_form(request, wl, [str(exc)], db)
    for k, v in data.model_dump().items():
        setattr(wl, k, v)
    if wl.active:
        backfill_watchlist(db, wl, 48)
    db.commit()
    return RedirectResponse(f"/listas/{wl.id}", status_code=303)


@router.get("/ofertas/{product_id}", response_class=HTMLResponse)
def offer_detail(request: Request, product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    history = db.execute(
        select(PricePoint, Product)
        .join(Product, Product.id == PricePoint.product_id)
        .where(or_(Product.id == product_id, Product.fingerprint == product.fingerprint))
        .order_by(PricePoint.seen_at)
    ).all()
    prices = [pp.price for pp, _ in history]
    points = ""
    if len(prices) >= 2:
        lo, hi = min(prices), max(prices)
        span = (hi - lo) or 1
        n = len(prices) - 1
        points = " ".join(f"{i * 600 / n:.1f},{110 - (p - lo) / span * 100:.1f}" for i, p in enumerate(prices))
    return templates.TemplateResponse(
        request, "offer.html", {"p": product, "history": history, "points": points}
    )
