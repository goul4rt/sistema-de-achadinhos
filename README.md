# Achadinhos: caçador de promoções

Sistema que **procura promoções sozinho**, guarda o **histórico de preço** e deixa você
cadastrar várias **listas** ("air fryer até R$ 400", "tênis com 40%+ off", "games na Amazon"...).
Cada oferta nova é avaliada contra todas as listas, e o que casar vira um **achado** com
score de "promoção real". Os achados ficam disponíveis por API e webhook para a fase 2
(disparo para grupos, canais e nichos).

Esta é a fase 1 (coleta + listas). O disparo para Telegram e WhatsApp ainda não existe, mas
a "caixa de saída" (`/api/matches` + webhook) já está pronta para ele.

## O que funciona hoje (testado em 13/10/2026)

| Fonte | Situação | Precisa de quê |
|---|---|---|
| **Promobit** | ✅ funcionando sem credencial. ~130 ofertas por ciclo (4 páginas das mais recentes), de dezenas de lojas: Amazon, Mercado Livre, Magalu, Shopee, AliExpress, Netshoes, Kabum etc. | nada |
| **Shopee Afiliados** (API oficial GraphQL) | ✅ implementada, liga sozinha com as chaves. Busca ativa pelas palavras-chave das suas listas e já devolve o **seu** link de afiliado. | `SHOPEE_APP_ID` + `SHOPEE_SECRET` (painel de afiliado > Open API) |
| **AliExpress Afiliados** (API oficial) | ✅ implementada, liga sozinha com as chaves. Busca ativa com preço em BRL e link de afiliado. | `ALIEXPRESS_APP_KEY` + `ALIEXPRESS_APP_SECRET` (+ `ALIEXPRESS_TRACKING_ID`) |
| Mercado Livre `/sites/MLB/search` | ❌ dá 403 (confirmado aqui também). Ficou de fora. | — |
| Pelando / Hardmob | ❌ Cloudflare bloqueia a partir de datacenter. Não incluí. | — |
| Amazon Creators API | ⏳ depende de 10 vendas em 30 dias. Fica para quando você tiver. | — |

> Shopee e AliExpress foram implementados com a assinatura oficial de cada API e têm testes
> unitários, mas **não puderam ser testados de ponta a ponta sem credenciais**. Se der erro com
> as suas chaves, a mensagem aparece em "Últimas coletas" no painel.

## Rodando

### Opção 1: Python (3.11+)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env                                   # opcional
python -m achadinhos serve                             # http://localhost:8000
```

Na subida ele cria o banco SQLite em `data/achadinhos.db`. A primeira coleta roda em ~5
segundos e depois a cada `COLLECT_INTERVAL_MINUTES` (padrão: 10).

### Opção 2: Docker

```bash
docker compose up -d                                   # http://localhost:8000
```

Para usar Postgres: `docker compose --profile postgres up -d` e no `.env` coloque
`DATABASE_URL=postgresql+psycopg://achadinhos:achadinhos@postgres:5432/achadinhos`.

### Outros comandos

```bash
python -m achadinhos collect            # roda uma coleta agora e sai (bom para cron)
python -m achadinhos collect --source promobit
python -m achadinhos sources            # status das fontes
pip install -e ".[dev]" && pytest       # testes
```

## Como funcionam as listas

No painel (`/listas`) ou pela API, cada lista tem:

- **Palavras-chave**: separadas por vírgula. Basta um termo casar. Dentro de um termo, **todas**
  as palavras precisam aparecer, em qualquer ordem, sem acento e sem diferença de maiúsculas.
  Palavras com 3 letras ou mais também casam como prefixo (`fone` pega `fones`). Use
  `"aspas"` para exigir a frase exata. Sem palavra-chave, a lista aceita qualquer oferta que
  passe nos outros filtros.
- **Excluir se contiver**: `capa, película, usado`.
- **Lojas** e **categorias**: trecho do nome, ex.: `amazon`, `mercado livre`, `games`.
- **Preço mínimo e máximo**, **desconto mínimo (%)**, **score mínimo**, **só com cupom**.
- **Fontes**: limita a lista a Promobit, Shopee e/ou AliExpress.
- **Nicho**: rótulo livre (casa, bebê, games…) para segmentar o disparo depois.
- **Webhook**: URL que recebe um POST a cada novo achado.

Ao criar ou salvar uma lista, ela é aplicada às ofertas das **últimas 48 h**, então você já vê
resultado na hora. O botão **"Testar nas ofertas das últimas 72 h"** mostra o que a lista pegaria
sem gravar nada, o que ajuda a calibrar os filtros.

Nas fontes com busca (Shopee e AliExpress), as palavras-chave das listas ativas viram as buscas
feitas a cada ciclo (até 30 termos por fonte).

### Deduplicação

- O mesmo anúncio não gera um achado novo na mesma lista, a não ser que o preço **caia 5% ou
  mais** em relação ao último achado.
- Repostagens do mesmo produto (mesma loja e mesmo título normalizado) dentro de **7 dias** são
  tratadas como o mesmo item.

## Score de "promoção real" (0 a 100)

O preço "de" riscado que a loja informa pode ser maquiado (o exemplo do Procon-SP na pesquisa),
então o score dá mais peso ao **histórico que o próprio sistema observou**:

| Sinal | Efeito |
|---|---|
| % de desconto sobre o "de" da loja | até +30 (sinal fraco) |
| Abaixo da mediana de 90 dias | até +40 |
| Menor preço do período | +15 |
| Acima da mediana | −15 |
| "De" maior que o máximo já visto (desconto inflado) | −10 |
| Preço subiu nos 30 dias antes da oferta | −10 |
| Popularidade (likes, vendas) | até +10 |
| Tem cupom | +5 |

O histórico é agrupado pelo *fingerprint* do produto, então repostagens alimentam a mesma série.
Nos primeiros dias o histórico ainda é curto e o score se apoia no desconto informado. Cada
achado traz a lista de motivos (ex.: "23% abaixo da mediana de 90 dias").

## Integração com a fase 2 (disparo)

**Feed incremental (pull):** guarde o maior `id` que você já processou e peça os próximos:

```bash
curl "http://localhost:8000/api/matches?after_id=0&limit=100"
curl "http://localhost:8000/api/matches?after_id=1234&min_score=40"
curl "http://localhost:8000/api/watchlists/3/matches?after_id=0"
```

**Webhook (push):** se a lista tiver `webhook_url`, cada achado novo gera um

```json
POST <webhook_url>
{"event": "match.created",
 "match": {"id": 57, "watchlist_id": 3, "watchlist_name": "Air fryer", "niche": "casa",
           "price": 299.9, "score": 62.5, "reasons": ["palavra-chave: air fryer", "..."],
           "product": {"title": "...", "store": "Amazon", "url": "...", "affiliate_url": "...",
                       "image_url": "...", "old_price": 499.9, "discount_pct": 40.0, "coupon": "..."}}}
```

A entrega do webhook é feita uma vez, sem nova tentativa. O status fica salvo no achado e
aparece no painel.

Documentação interativa de todos os endpoints: **`/docs`**. Os principais:

| Método | Rota | Para quê |
|---|---|---|
| GET/POST | `/api/watchlists` | listar / criar listas |
| GET/PUT/DELETE | `/api/watchlists/{id}` | ver / editar / apagar |
| POST | `/api/watchlists/preview` | testar critérios sem salvar |
| GET | `/api/matches` | feed de achados (cursor `after_id`) |
| GET | `/api/offers?q=&store=&source=` | ofertas coletadas |
| GET | `/api/offers/{id}/history` | histórico de preço |
| POST | `/api/collect?wait=true` | forçar coleta |
| GET | `/api/runs` | log das coletas |
| GET | `/api/health` | status e fontes |

## Arquitetura

```
achadinhos/
  sources/        adaptadores por fonte: fetch_latest() (feed) e/ou search(query)
    promobit.py   API JSON do site + fallback no HTML (__NEXT_DATA__)
    shopee.py     GraphQL oficial, assinatura SHA256
    aliexpress.py API oficial, assinatura HMAC-SHA256
  pipeline.py     RawOffer -> Product + PricePoint -> avaliação -> Match (+ webhook)
  rules.py        filtros das listas + score de promoção real
  collector.py    rodada de coleta (feeds + buscas guiadas pelas listas), log por fonte
  scheduler.py    APScheduler dentro do processo
  api.py, web.py  API JSON e painel
  models.py       products, price_points, watchlists, matches, collection_runs
```

Para adicionar uma loja, crie uma classe `Source` em `sources/` que devolve uma lista de
`RawOffer` e registre em `sources/__init__.py`. Filtros, histórico, dedup, score e webhook
funcionam sem mudar mais nada.

Funciona com SQLite (zero configuração) ou Postgres (`DATABASE_URL`). Para volume alto, o
caminho natural (como está na pesquisa) é trocar o APScheduler por filas (Celery/RQ/BullMQ) e
particionar `price_points`.

## Próximos passos sugeridos

1. Colocar as chaves da **Shopee** e do **AliExpress** no `.env`. São as fontes oficiais e já
   geram o seu link de afiliado.
2. **Fase 2, Telegram primeiro**: um worker que lê `/api/matches?after_id=` (ou recebe o
   webhook), monta o card e posta no canal ou grupo do nicho, respeitando ≤20 msg/min por grupo.
3. Conversão de link de afiliado na hora do envio (Amazon com tag, Awin/Lomadee para
   Magalu/Casas Bahia etc.), com subId por lista para medir conversão.
4. WhatsApp por último, com número dedicado e fila anti-ban.
5. Classificação de nicho com LLM em lote e dedup entre lojas por EAN/modelo.

## Avisos

- A API do **Promobit** usada aqui é a mesma que o site deles usa, mas **não é pública nem
  documentada**: pode mudar ou bloquear sem aviso. Use como **sinal** de oferta, com a frequência
  padrão (1 rodada a cada 10 min). Republicar o conteúdo deles na íntegra esbarra nos termos de
  uso. O link que vem do Promobit passa pelo redirecionador deles (com a afiliação deles). Para
  ganhar comissão, você precisa do link original + o seu link de afiliado, que vem das APIs
  oficiais (Shopee/AliExpress já entregam o `affiliate_url`).
- Amazon Associados restringe link direto em grupos fechados. Veja a seção de compliance da pesquisa.
- Não é aconselhamento jurídico. LGPD e termos de afiliado: valide com um advogado.
