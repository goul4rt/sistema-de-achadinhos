"""Aplicação FastAPI: API JSON em /api, painel em /, docs em /docs."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import router as api_router
from .db import create_all
from .scheduler import start_scheduler, stop_scheduler
from .web import router as web_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_all()
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title="Achadinhos", version=__version__, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
