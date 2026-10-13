"""Orquestra uma rodada de coleta: feeds + buscas ativas guiadas pelas listas."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .models import CollectionRun, Watchlist, utcnow
from .pipeline import deliver_webhooks, ingest
from .sources import Source, get_sources

log = logging.getLogger(__name__)

MAX_SEARCH_QUERIES_PER_SOURCE = 30
_lock = threading.Lock()


@dataclass
class CollectionSummary:
    runs: list[dict] = field(default_factory=list)
    skipped: bool = False

    @property
    def total_matches(self) -> int:
        return sum(r["matches"] for r in self.runs)


def make_client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        timeout=s.http_timeout_seconds,
        headers={"User-Agent": s.user_agent, "Accept": "application/json, text/html;q=0.9"},
        follow_redirects=True,
    )


def search_queries_for(source: Source) -> list[str]:
    """Termos de busca = palavras-chave das listas ativas que aceitam essa fonte."""
    with session_scope() as session:
        lists = session.execute(select(Watchlist).where(Watchlist.active.is_(True))).scalars().all()
        queries: list[str] = []
        for wl in lists:
            if wl.sources and source.name not in wl.sources:
                continue
            for kw in wl.keywords or []:
                q = kw.strip().strip('"').strip()
                if q and q.lower() not in {x.lower() for x in queries}:
                    queries.append(q)
    return queries[:MAX_SEARCH_QUERIES_PER_SOURCE]


def _run_one(source: Source, client: httpx.Client, query: str = "") -> dict:
    with session_scope() as session:
        run = CollectionRun(source=source.name, query=query, started_at=utcnow())
        session.add(run)
        session.flush()
        run_id = run.id
    error = ""
    stats = {"fetched": 0, "created": 0, "updated": 0, "matches": 0}
    try:
        raws = source.search(query, client) if query else source.fetch_latest(client)
        with session_scope() as session:
            result = ingest(session, raws)
            session.commit()  # grava antes de avisar o webhook
            deliver_webhooks(session, result.new_matches)
            stats = {
                "fetched": result.fetched,
                "created": result.created,
                "updated": result.updated,
                "matches": len(result.new_matches),
            }
    except Exception as exc:  # uma fonte quebrada não derruba as outras
        log.exception("coleta falhou: %s %s", source.name, query)
        error = f"{type(exc).__name__}: {exc}"[:1000]
    with session_scope() as session:
        run = session.get(CollectionRun, run_id)
        run.finished_at = utcnow()
        run.error = error
        for k, v in stats.items():
            setattr(run, k, v)
        session.flush()
        from .serializers import run_to_dict

        return run_to_dict(run)


def run_collection(only: list[str] | None = None) -> CollectionSummary:
    if not _lock.acquire(blocking=False):
        log.info("coleta já em andamento; pulando")
        return CollectionSummary(skipped=True)
    try:
        summary = CollectionSummary()
        with make_client() as client:
            for source in get_sources():
                if only and source.name not in only:
                    continue
                if not source.enabled():
                    continue
                if source.supports_feed:
                    summary.runs.append(_run_one(source, client))
                if source.supports_search:
                    for q in search_queries_for(source):
                        summary.runs.append(_run_one(source, client, q))
        log.info(
            "coleta concluída: %d execuções, %d novos matches", len(summary.runs), summary.total_matches
        )
        return summary
    finally:
        _lock.release()
