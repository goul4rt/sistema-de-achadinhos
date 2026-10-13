from datetime import datetime, timedelta

from sqlalchemy import func, select

from achadinhos.models import Match, PricePoint, Product, Watchlist, utcnow
from achadinhos.pipeline import ingest, preview_watchlist
from achadinhos.rules import evaluate, history_stats, match_watchlist
from achadinhos.sources.base import RawOffer

T0 = datetime(2026, 10, 1, 12, 0)


def raw(ext="1", title="Air Fryer Mondial 4L", price=300.0, old=None, store="Amazon", **kw):
    return RawOffer(source="test", external_id=ext, title=title, price=price, old_price=old, store=store, **kw)


def add_list(session, **kw):
    wl = Watchlist(name=kw.pop("name", "lista"), **kw)
    session.add(wl)
    session.commit()
    return wl


def count(session, model):
    return session.scalar(select(func.count(model.id)))


def test_match_filters(session):
    wl = Watchlist(name="x", keywords=["air fryer"], exclude_keywords=["cesto"], stores=["amazon"],
                   max_price=400, min_discount=10)
    p = Product(source="test", title="Air Fryer Mondial", store="Amazon.com.br", price=300, discount_pct=20,
                keywords="", category="")
    assert match_watchlist(wl, p, 0)[0]
    p.title = "Cesto para Air Fryer"
    assert not match_watchlist(wl, p, 0)[0]
    p.title, p.price = "Air Fryer Mondial", 500
    assert match_watchlist(wl, p, 0) == (False, ["acima do preço máximo"])
    p.price, p.store = 300, "Magalu"
    assert not match_watchlist(wl, p, 0)[0]


def test_ingest_creates_products_points_and_matches(session):
    add_list(session, keywords=["air fryer"])
    res = ingest(session, [raw(), raw("2", "Notebook Dell")], now=T0)
    session.commit()
    assert (res.created, len(res.new_matches)) == (2, 1)
    assert count(session, PricePoint) == 2


def test_same_price_does_not_rematch_but_drop_does(session):
    add_list(session, keywords=["air fryer"])
    ingest(session, [raw(price=300)], now=T0)
    res = ingest(session, [raw(price=300)], now=T0 + timedelta(hours=1))
    assert len(res.new_matches) == 0 and res.updated == 0
    res = ingest(session, [raw(price=295)], now=T0 + timedelta(hours=2))
    assert len(res.new_matches) == 0  # queda < 5%
    res = ingest(session, [raw(price=270)], now=T0 + timedelta(hours=3))
    assert len(res.new_matches) == 1
    session.commit()
    assert count(session, Match) == 2


def test_repost_of_same_product_is_deduplicated(session):
    add_list(session, keywords=["air fryer"])
    ingest(session, [raw("1", "Air Fryer Mondial 4L")], now=T0)
    res = ingest(session, [raw("2", "air fryer mondial 4l")], now=T0 + timedelta(days=1))
    assert res.created == 1 and len(res.new_matches) == 0
    res = ingest(session, [raw("3", "Air Fryer Mondial 4L")], now=T0 + timedelta(days=9))
    assert len(res.new_matches) == 1  # fora da janela de 7 dias


def test_score_uses_history_lowest_price_and_inflated_old_price(session):
    for i, price in enumerate([400, 410, 390, 405]):
        ingest(session, [raw(f"h{i}", price=price)], now=T0 + timedelta(days=i * 5))
    session.commit()
    p = session.execute(select(Product).where(Product.external_id == "h0")).scalar_one()
    p.price, p.old_price, p.discount_pct = 300, 900, 66.7
    ev = evaluate(p, history_stats(session, p.fingerprint, T0 + timedelta(days=30)))
    joined = " | ".join(ev.reasons)
    assert "menor preço" in joined and "abaixo da mediana" in joined and "inflado" in joined
    p.price, p.old_price, p.discount_pct = 450, None, None
    ev2 = evaluate(p, history_stats(session, p.fingerprint, T0 + timedelta(days=30)))
    assert ev2.score < ev.score and "acima da mediana" in " ".join(ev2.reasons)


def test_min_score_filter(session):
    add_list(session, keywords=["air fryer"], min_score=30)
    res = ingest(session, [raw(price=300, old=310)], now=T0)  # desconto pequeno, sem histórico
    assert len(res.new_matches) == 0
    res = ingest(session, [raw("9", "Air Fryer Philco", price=100, old=300)], now=T0)
    assert len(res.new_matches) == 1


def test_preview_does_not_write(session):
    ingest(session, [raw()], now=utcnow())
    session.commit()
    wl = Watchlist(name="tmp", keywords=["fryer"])
    found = preview_watchlist(session, wl, hours=24)
    assert len(found) == 1 and count(session, Match) == 0
