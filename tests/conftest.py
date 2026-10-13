import pytest

from achadinhos import db
from achadinhos.config import Settings, set_settings


@pytest.fixture(autouse=True)
def fresh_db():
    set_settings(Settings(database_url="sqlite://", scheduler_enabled=False))
    db.init_engine("sqlite://")
    db.create_all()
    yield
    db.get_engine().dispose()


@pytest.fixture
def session():
    s = db.new_session()
    yield s
    s.close()
