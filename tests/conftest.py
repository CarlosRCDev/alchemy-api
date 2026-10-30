import json
from pathlib import Path

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, insert

from alchemy_api.utils import read_cnx_data

# Every settings file in tests/settings is a test run: all tests are executed once per file
SETTINGS_DIR = Path(__file__).resolve().parent / "settings"
SETTINGS_FILES = sorted(SETTINGS_DIR.glob("*.json"))

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


@pytest.fixture(params=SETTINGS_FILES, ids=lambda path: path.stem)
def settings(request):
    with open(request.param) as f:
        return json.load(f)["database"]


@pytest.fixture
def backend(settings):
    return settings["type"]


@pytest.fixture
def db_cfg(settings):
    # Full Conexion config (kwargs), logs included, as given by the settings file
    # read_cnx_data pops some keys, so it gets a copy
    cnx_data, cnx_data_extra, show_query, modifiers, config_log = read_cnx_data(dict(settings))
    if settings["type"] == "sqlite":
        Path(settings["path"]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(cnx_data, **cnx_data_extra)
    metadata = MetaData()
    users = _users_table(metadata)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(users), ROWS)
    yield {
        "cnx_data": cnx_data,
        "cnx_data_extra": cnx_data_extra,
        "show_query": show_query,
        "modifiers": modifiers,
        "config_log": config_log,
    }
    metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def cnx_cfg(db_cfg):
    # Without modifiers/show_query: generic tests expect lowercase keys
    return {key: db_cfg[key] for key in ("cnx_data", "cnx_data_extra", "config_log")}


@pytest.fixture
def async_db_cfg(cnx_cfg):
    # oracle+oracledb works with create_async_engine (async driver mode); sqlite needs aiosqlite
    if cnx_cfg["cnx_data"].startswith("sqlite://"):
        return {**cnx_cfg, "cnx_data": cnx_cfg["cnx_data"].replace("sqlite://", "sqlite+aiosqlite://", 1)}
    return cnx_cfg


@pytest.fixture
def cnx(cnx_cfg):
    from alchemy_api import Conexion
    return Conexion(**cnx_cfg)


@pytest.fixture
def cnx_no_raise(cnx_cfg):
    from alchemy_api import Conexion
    return Conexion(**cnx_cfg, _raise=False)
