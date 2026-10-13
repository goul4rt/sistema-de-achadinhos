"""Configuração via variáveis de ambiente (opcionalmente lidas de um arquivo .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Carrega KEY=VALUE de um .env sem sobrescrever o ambiente real."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


@dataclass
class Settings:
    database_url: str = "sqlite:///data/achadinhos.db"
    scheduler_enabled: bool = True
    collect_interval_minutes: int = 10
    http_timeout_seconds: int = 20
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    promobit_enabled: bool = True
    promobit_pages: int = 4
    shopee_app_id: str = ""
    shopee_secret: str = ""
    aliexpress_app_key: str = ""
    aliexpress_app_secret: str = ""
    aliexpress_tracking_id: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(Path(os.environ.get("ACHADINHOS_ENV_FILE", ".env")))
        return cls(
            database_url=os.environ.get("DATABASE_URL", cls.database_url),
            scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
            collect_interval_minutes=_int("COLLECT_INTERVAL_MINUTES", 10),
            http_timeout_seconds=_int("HTTP_TIMEOUT_SECONDS", 20),
            promobit_enabled=_bool("PROMOBIT_ENABLED", True),
            promobit_pages=_int("PROMOBIT_PAGES", 4),
            shopee_app_id=os.environ.get("SHOPEE_APP_ID", ""),
            shopee_secret=os.environ.get("SHOPEE_SECRET", ""),
            aliexpress_app_key=os.environ.get("ALIEXPRESS_APP_KEY", ""),
            aliexpress_app_secret=os.environ.get("ALIEXPRESS_APP_SECRET", ""),
            aliexpress_tracking_id=os.environ.get("ALIEXPRESS_TRACKING_ID", ""),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def set_settings(settings: Settings) -> None:
    """Usado em testes para injetar configuração."""
    global _settings
    _settings = settings
