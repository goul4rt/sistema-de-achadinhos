"""Agendador em processo (APScheduler). Para escalar, troque por Celery/RQ/BullMQ."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .collector import run_collection
from .config import get_settings

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    s = get_settings()
    if not s.scheduler_enabled or _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_collection,
        "interval",
        minutes=max(1, s.collect_interval_minutes),
        id="collect",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
    )
    _scheduler.start()
    log.info("agendador iniciado: coleta a cada %s min", s.collect_interval_minutes)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run() -> datetime | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("collect")
    return job.next_run_time if job else None
