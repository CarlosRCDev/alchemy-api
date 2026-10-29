import json
import os
from pathlib import Path

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, insert

ROOT = Path(__file__).resolve().parent.parent

# Oracle tests run only when this env var points to a settings file, e.g.
#   TEST_ORACLE_CONFIG=settings/config_docker_oracle.json uv run pytest
ORACLE_CONFIG = os.getenv("TEST_ORACLE_CONFIG")
BACKENDS = ["sqlite", "oracle"] if ORACLE_CONFIG else ["sqlite"]

ROWS = [
    {"id": 1, "name": "ana", "age": 30},
    {"id": 2, "name": "luis", "age": 25},
    {"id": 3, "name": "marta", "age": 30},
    {"id": 4, "name": "pepa", "age": 40},
]


def _users_table(metadata):
    return Table(
        "users", metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("name", String(50)),
        Column("age", Integer),
        Column("created", DateTime),
    )


def _oracle_url():
    from alchemy_api.utils import read_cnx_data
    with open(ROOT / ORACLE_CONFIG) as f:
        cfg = json.load(f)["database"]
    return read_cnx_data(cfg)[0]


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param


@pytest.fixture
def db_url(backend, tmp_path):
    url = _oracle_url() if backend == "oracle" else f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url)
    metadata = MetaData()
    users = _users_table(metadata)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(users), ROWS)
    yield url
    metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def async_db_url(db_url, backend):
    # oracle+oracledb works with create_async_engine (async driver mode)
    return db_url.replace("sqlite://", "sqlite+aiosqlite://", 1) if backend == "sqlite" else db_url


@pytest.fixture
def cnx(db_url):
    from alchemy_api import Conexion
    return Conexion(db_url)


@pytest.fixture
def cnx_no_raise(db_url):
    from alchemy_api import Conexion
    return Conexion(db_url, _raise=False)
