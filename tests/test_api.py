from achadinhos.models import utcnow

import httpx
from fastapi.testclient import TestClient

from achadinhos import pipeline
from achadinhos.app import create_app
from achadinhos.db import session_scope
from achadinhos.sources.base import RawOffer


def seed():
    with session_scope() as s:
        pipeline.ingest(s, [
            RawOffer(source="promobit", external_id="1", title="Tênis Nike Revolution", price=199, old_price=399, store="Netshoes"),
            RawOffer(source="promobit", external_id="2", title="Smart TV 50 4K", price=2100, store="Amazon"),
        ], now=utcnow())


def test_watchlist_crud_backfill_and_matches_feed():
    with TestClient(create_app()) as client:
        seed()
        r = client.post("/api/watchlists", json={"name": "Tênis", "keywords": "tenis, sapatenis", "min_discount": 30})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["keywords"] == ["tenis", "sapatenis"] and body["backfilled_matches"] == 1
        wl_id = body["id"]

        feed = client.get("/api/matches").json()
        assert len(feed) == 1 and feed[0]["product"]["title"].startswith("Tênis")
        assert client.get(f"/api/matches?after_id={feed[0]['id']}").json() == []

        r = client.put(f"/api/watchlists/{wl_id}", json={"name": "Tênis", "keywords": ["tv"]})
        assert r.json()["keywords"] == ["tv"]
        assert client.delete(f"/api/watchlists/{wl_id}").status_code == 204
        assert client.get(f"/api/watchlists/{wl_id}").status_code == 404


def test_preview_and_validation():
    with TestClient(create_app()) as client:
        seed()
        r = client.post("/api/watchlists/preview", json={"name": "x", "max_price": 500})
        assert [x["product"]["external_id"] for x in r.json()] == ["1"]
        assert client.post("/api/watchlists", json={"name": "x", "webhook_url": "ftp://a"}).status_code == 422
        assert client.post("/api/watchlists", json={"name": ""}).status_code == 422


def test_html_pages_and_form():
    with TestClient(create_app()) as client:
        seed()
        assert client.get("/").status_code == 200
        r = client.post("/listas", data={"name": "TV", "keywords": "smart tv", "active": "on", "max_price": "3000"},
                        follow_redirects=False)
        assert r.status_code == 303
        page = client.get(r.headers["location"])
        assert page.status_code == 200 and "Smart TV 50 4K" in page.text
        assert client.get(r.headers["location"] + "?preview=1").status_code == 200
        assert client.get("/ofertas/1").status_code == 200
        assert client.get("/listas").status_code == 200


def test_webhook_delivery():
    received = []

    def handler(request: httpx.Request):
        received.append(request.read())
        return httpx.Response(200)

    with session_scope() as s:
        from achadinhos.models import Watchlist

        wl = Watchlist(name="hook", keywords=["tv"], webhook_url="https://example.test/hook")
        s.add(wl)
        s.flush()
        res = pipeline.ingest(s, [RawOffer(source="t", external_id="1", title="Smart TV", price=10)])
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            pipeline.deliver_webhooks(s, res.new_matches, c)
        assert res.new_matches[0].webhook_status == "http 200"
    assert b'"match.created"' in received[0] and b"Smart TV" in received[0]
