import hashlib
import json
from pathlib import Path

import httpx

from achadinhos.sources import aliexpress, promobit, shopee

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "promobit_offers.json").read_text())


def test_promobit_parse_skips_invalid_and_fixes_old_price():
    offers = promobit.parse_offers(FIXTURE["offers"])
    ids = {o.external_id for o in offers}
    assert "3108132" not in ids  # preço 0 -> não é produto
    by_id = {o.external_id: o for o in offers}
    magalu = by_id["3100013"]
    assert magalu.old_price is None  # "de" 0,01 é lixo
    tv = by_id["3110810"]
    assert tv.old_price is None and tv.price == 2890
    sueter = by_id["3111017"]
    assert sueter.old_price == 118.52 and sueter.discount_pct == 52.0
    assert sueter.url.startswith("https://www.promobit.com.br/oferta/")
    assert sueter.image_url.startswith("https://i.promobit.com.br/")
    assert sueter.published_at is not None and sueter.published_at.tzinfo is None


def test_promobit_skips_coupon_posts():
    item = dict(FIXTURE["offers"][1], offer_price_type="COUPON")
    assert promobit.parse_offer(item) is None


def test_promobit_accepts_camel_case_from_html():
    camel = {"offerId": 1, "offerTitle": "Mouse Gamer", "offerPrice": 99.9, "offerOldPrice": 150,
             "storeName": "Kabum", "offerSlug": "mouse-1", "offerStatusName": "APPROVED"}
    html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
        {"props": {"pageProps": {"serverOffers": {"offers": [camel]}}}}) + "</script>"
    offers = promobit.parse_offers(promobit.parse_home_html(html))
    assert len(offers) == 1 and offers[0].store == "Kabum" and offers[0].old_price == 150


def test_promobit_fetch_paginates_with_after_cursor(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append(dict(request.url.params))
        if "after" not in request.url.params:
            return httpx.Response(200, json={"after": "c1", "offers": FIXTURE["offers"][:3]})
        return httpx.Response(200, json={"after": None, "offers": FIXTURE["offers"][3:]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        offers = promobit.PromobitSource().fetch_latest(client)
    assert len(calls) == 2 and calls[1]["after"] == "c1"
    assert len(offers) == 5


def test_promobit_falls_back_to_home_html():
    camel = {"offerId": 7, "offerTitle": "Teclado", "offerPrice": 50, "offerSlug": "t-7"}
    html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
        {"props": {"pageProps": {"serverOffers": {"offers": [camel]}}}}) + "</script>"

    def handler(request: httpx.Request):
        if request.url.host == "api.promobit.com.br":
            return httpx.Response(503)
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        offers = promobit.PromobitSource().fetch_latest(client)
    assert [o.external_id for o in offers] == ["7"]


def test_shopee_signature_and_parse():
    payload = '{"query":"x"}'
    expected = hashlib.sha256(b"123" + b"1700000000" + payload.encode() + b"sec").hexdigest()
    assert shopee.auth_header("123", "sec", payload, 1700000000) == (
        f"SHA256 Credential=123, Timestamp=1700000000, Signature={expected}"
    )
    offers = shopee.parse_nodes([
        {"itemId": 9, "productName": "Air Fryer", "priceMin": "200.00", "priceDiscountRate": 50,
         "offerLink": "https://s.shopee.com.br/x", "shopName": "Loja", "sales": 10}
    ])
    assert offers[0].old_price == 400.0 and offers[0].affiliate_url.startswith("https://s.shopee")


def test_aliexpress_signature_is_sorted_hmac():
    sig = aliexpress.sign({"b": "2", "a": "1"}, "secret")
    import hmac
    assert sig == hmac.new(b"secret", b"a1b2", hashlib.sha256).hexdigest().upper()
    offers = aliexpress.parse_products([
        {"product_id": 1, "product_title": "Fone", "target_sale_price": "30.5",
         "target_original_price": "61", "promotion_link": "https://s.click.aliexpress.com/x"}
    ])
    assert offers[0].discount_pct == 50.0
