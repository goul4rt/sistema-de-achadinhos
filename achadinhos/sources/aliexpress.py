"""AliExpress Affiliate API (Open Platform) - API oficial.

Requer app key/secret do portal de afiliados (openservice.aliexpress.com) e um
tracking_id. Usa aliexpress.affiliate.product.query com preços em BRL para o Brasil.
Assinatura: HMAC-SHA256(secret, concat(chave+valor dos parâmetros ordenados)), hex maiúsculo.
"""

from __future__ import annotations

import hashlib
import hmac
import time

import httpx

from ..config import get_settings
from .base import RawOffer, Source, SourceError, to_float

ENDPOINT = "https://api-sg.aliexpress.com/sync"
FIELDS = (
    "product_id,product_title,target_sale_price,target_original_price,discount,"
    "product_main_image_url,product_detail_url,promotion_link,first_level_category_name,"
    "second_level_category_name,shop_name,lastest_volume,evaluate_rate,commission_rate"
)


def sign(params: dict, secret: str) -> str:
    base = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest().upper()


def parse_products(products: list[dict]) -> list[RawOffer]:
    out = []
    for p in products:
        price = to_float(p.get("target_sale_price"))
        if not price or not p.get("product_id"):
            continue
        category = " / ".join(
            x for x in (p.get("first_level_category_name"), p.get("second_level_category_name")) if x
        )
        out.append(
            RawOffer(
                source="aliexpress",
                external_id=str(p["product_id"]),
                title=p.get("product_title") or "",
                price=price,
                old_price=to_float(p.get("target_original_price")),
                url=p.get("product_detail_url") or "",
                affiliate_url=p.get("promotion_link") or "",
                image_url=p.get("product_main_image_url") or "",
                store="AliExpress" + (f" / {p['shop_name']}" if p.get("shop_name") else ""),
                category=category,
                popularity=int(p.get("lastest_volume") or 0),
                extra={
                    "commission_rate": p.get("commission_rate"),
                    "evaluate_rate": p.get("evaluate_rate"),
                },
            )
        )
    return out


class AliExpressSource(Source):
    name = "aliexpress"
    label = "AliExpress Afiliados (API oficial)"
    supports_search = True

    def enabled(self) -> bool:
        s = get_settings()
        return bool(s.aliexpress_app_key and s.aliexpress_app_secret)

    def status(self) -> str:
        return "ativa" if self.enabled() else "sem credenciais (ALIEXPRESS_APP_KEY/ALIEXPRESS_APP_SECRET)"

    def search(self, query: str, client: httpx.Client, limit: int = 50) -> list[RawOffer]:
        s = get_settings()
        params = {
            "app_key": s.aliexpress_app_key,
            "method": "aliexpress.affiliate.product.query",
            "sign_method": "sha256",
            "timestamp": str(int(time.time() * 1000)),
            "keywords": query,
            "page_no": "1",
            "page_size": str(limit),
            "sort": "LAST_VOLUME_DESC",
            "target_currency": "BRL",
            "target_language": "PT",
            "ship_to_country": "BR",
            "fields": FIELDS,
        }
        if s.aliexpress_tracking_id:
            params["tracking_id"] = s.aliexpress_tracking_id
        params["sign"] = sign(params, s.aliexpress_app_secret)
        resp = client.post(ENDPOINT, data=params)
        resp.raise_for_status()
        data = resp.json()
        if "error_response" in data:
            err = data["error_response"]
            raise SourceError(f"AliExpress: {err.get('code')} {err.get('msg')}")
        result = (
            data.get("aliexpress_affiliate_product_query_response", {})
            .get("resp_result", {})
            .get("result", {})
        )
        products = (result.get("products") or {}).get("product") or []
        return parse_products(products)
