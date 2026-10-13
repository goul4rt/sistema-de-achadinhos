"""Promobit: ofertas curadas pela comunidade, sem credencial.

Usa a mesma API JSON que o site consome (api.promobit.com.br/offers). Não é uma API
pública documentada: pode mudar sem aviso. Se ela falhar, cai para o JSON embutido
na home (__NEXT_DATA__). Trate como "sinal" de oferta; o link da loja passa pelo
redirecionador do Promobit (com a afiliação deles).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx

from ..config import get_settings
from .base import RawOffer, Source, SourceError, to_float

API_URL = "https://api.promobit.com.br/offers"
SITE_URL = "https://www.promobit.com.br"
IMAGE_URL = "https://i.promobit.com.br"
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _snake(d: dict) -> dict:
    return {(_CAMEL.sub("_", k).lower() if not k.islower() else k): v for k, v in d.items()}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def parse_offer(item: dict) -> RawOffer | None:
    o = _snake(item)
    price = to_float(o.get("offer_price"))
    title = (o.get("offer_title") or "").strip()
    if not o.get("offer_id") or not title or not price or price <= 0:
        return None
    if o.get("offer_status_name") not in (None, "APPROVED"):
        return None
    if o.get("offer_price_type") == "COUPON":  # posts de cupom/aviso, não são produtos
        return None
    photo = o.get("offer_photo") or ""
    if photo and not photo.startswith("http"):
        photo = IMAGE_URL + "/" + photo.lstrip("/")
    slug = o.get("offer_slug") or ""
    category = " / ".join(x for x in (o.get("category_name"), o.get("subcategory_name")) if x)
    published = _parse_dt(o.get("offer_published"))
    ratings = o.get("ratings") or {}
    return RawOffer(
        source="promobit",
        external_id=str(o["offer_id"]),
        title=title,
        price=price,
        old_price=to_float(o.get("offer_old_price")),
        url=f"{SITE_URL}/oferta/{slug}/" if slug else f"{SITE_URL}/Redirect/to/{o['offer_id']}/",
        image_url=photo,
        store=o.get("store_name") or o.get("store_domain") or "",
        category=category or (o.get("category_slug") or ""),
        keywords=o.get("suggestion_keywords") or "",
        coupon=(o.get("offer_coupon") or "").strip(),
        popularity=int(o.get("offer_likes") or 0) + int(ratings.get("all") or 0),
        published_at=published.astimezone(timezone.utc).replace(tzinfo=None) if published and published.tzinfo else published,
        extra={
            "store_domain": o.get("store_domain"),
            "price_type": o.get("offer_price_type"),
            "comments": o.get("offer_comments"),
            "engagement": o.get("offer_engagement_score"),
            "redirect_url": f"{SITE_URL}/Redirect/to/{o['offer_id']}/",
        },
    )


def parse_offers(items: list[dict]) -> list[RawOffer]:
    out = []
    for item in items:
        offer = parse_offer(item)
        if offer:
            out.append(offer)
    return out


def parse_home_html(html: str) -> list[dict]:
    m = _NEXT_DATA.search(html)
    if not m:
        raise SourceError("Promobit: __NEXT_DATA__ não encontrado na página")
    props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    items = list((props.get("serverOffers") or {}).get("offers") or [])
    items += list(props.get("serverFeaturedOffers") or [])
    return items


class PromobitSource(Source):
    name = "promobit"
    label = "Promobit (comunidade)"
    supports_feed = True

    def enabled(self) -> bool:
        return get_settings().promobit_enabled

    def fetch_latest(self, client: httpx.Client) -> list[RawOffer]:
        pages = max(1, get_settings().promobit_pages)
        items: list[dict] = []
        after = None
        try:
            for _ in range(pages):
                params = {"sort": "latest", "limit": 50}
                if after:
                    params["after"] = after
                resp = client.get(API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("offers") or []
                items.extend(batch)
                after = data.get("after")
                if not batch or not after:
                    break
        except (httpx.HTTPError, ValueError) as exc:
            if items:
                return parse_offers(items)
            resp = client.get(SITE_URL + "/")
            if resp.status_code != 200:
                raise SourceError(f"Promobit indisponível: {exc}; home HTTP {resp.status_code}")
            items = parse_home_html(resp.text)
        return parse_offers(items)
