"""Shopee Affiliate Open API (Brasil) - API oficial GraphQL.

Requer conta de afiliado + aprovação da Open API (AppID e Secret no painel
affiliate.shopee.com.br > Open API). Autenticação:
    Authorization: SHA256 Credential={AppId}, Timestamp={ts}, Signature={sha256(AppId+ts+payload+Secret)}
"""

from __future__ import annotations

import hashlib
import json
import time

import httpx

from ..config import get_settings
from .base import RawOffer, Source, SourceError, to_float

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"

PRODUCT_QUERY = """
query($keyword: String, $page: Int, $limit: Int, $sortType: Int) {
  productOfferV2(keyword: $keyword, page: $page, limit: $limit, sortType: $sortType) {
    nodes {
      itemId productName price priceMin priceMax priceDiscountRate
      commissionRate imageUrl productLink offerLink shopName sales ratingStar
    }
    pageInfo { page limit hasNextPage }
  }
}
""".strip()


def sign(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    return hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode("utf-8")).hexdigest()


def auth_header(app_id: str, secret: str, payload: str, timestamp: int | None = None) -> str:
    ts = int(timestamp if timestamp is not None else time.time())
    return f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={sign(app_id, secret, ts, payload)}"


def parse_nodes(nodes: list[dict]) -> list[RawOffer]:
    out = []
    for n in nodes:
        price = to_float(n.get("priceMin")) or to_float(n.get("price"))
        if not price or not n.get("itemId"):
            continue
        rate = to_float(n.get("priceDiscountRate")) or 0
        old = round(price / (1 - rate / 100), 2) if 0 < rate < 100 else None
        out.append(
            RawOffer(
                source="shopee",
                external_id=str(n["itemId"]),
                title=n.get("productName") or "",
                price=price,
                old_price=old,
                url=n.get("productLink") or "",
                affiliate_url=n.get("offerLink") or "",
                image_url=n.get("imageUrl") or "",
                store=f"Shopee / {n['shopName']}" if n.get("shopName") else "Shopee",
                popularity=int(n.get("sales") or 0),
                extra={
                    "commission_rate": n.get("commissionRate"),
                    "rating": n.get("ratingStar"),
                    "sales": n.get("sales"),
                },
            )
        )
    return out


class ShopeeSource(Source):
    name = "shopee"
    label = "Shopee Afiliados (API oficial)"
    supports_search = True

    def enabled(self) -> bool:
        s = get_settings()
        return bool(s.shopee_app_id and s.shopee_secret)

    def status(self) -> str:
        return "ativa" if self.enabled() else "sem credenciais (SHOPEE_APP_ID/SHOPEE_SECRET)"

    def search(self, query: str, client: httpx.Client, limit: int = 50) -> list[RawOffer]:
        s = get_settings()
        body = {
            "query": PRODUCT_QUERY,
            "variables": {"keyword": query, "page": 1, "limit": limit, "sortType": 2},
        }
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        resp = client.post(
            ENDPOINT,
            content=payload.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": auth_header(s.shopee_app_id, s.shopee_secret, payload),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise SourceError(f"Shopee: {data['errors'][0].get('message')}")
        nodes = ((data.get("data") or {}).get("productOfferV2") or {}).get("nodes") or []
        return parse_nodes(nodes)
