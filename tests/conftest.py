import json
from pathlib import Path

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, insert

from alchemy_api.permissions import read_roles
from alchemy_api.utils import read_cnx_data

# Every settings file in tests/settings is a test run: all tests are executed once per file
SETTINGS_DIR = Path(__file__).resolve().parent / "settings"
SETTINGS_FILES = sorted(SETTINGS_DIR.glob("*.json"))

ASYNC_DRIVERS = {
    "sqlite://": "sqlite+aiosqlite://",
    "mariadb+pymysql://": "mariadb+aiomysql://",
    "mysql+pymysql://": "mysql+aiomysql://",
}

NO_ASYNC_DRIVER = ("mssql+pymssql://",)

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
def settings_json(request):
    with open(request.param) as f:
        return json.load(f)


@pytest.fixture
def settings(settings_json):
    return settings_json["database"]


@pytest.fixture
def roles(settings_json):
    # {role: allowed operations} from the "roles" section, None if the file has no roles
    return read_roles(settings_json.get("roles"))


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
    # oracle+oracledb and postgresql+psycopg work with create_async_engine as they are;
    # sqlite, mariadb and mysql need their async driver
    # SQL Server's async driver (aioodbc) needs the system ODBC driver: not tested
    if cnx_cfg["cnx_data"].startswith(NO_ASYNC_DRIVER):
        pytest.skip(f"no async driver tested for {cnx_cfg['cnx_data'].split(':')[0]}")
    for sync_prefix, async_prefix in ASYNC_DRIVERS.items():
        if cnx_cfg["cnx_data"].startswith(sync_prefix):
            return {**cnx_cfg, "cnx_data": cnx_cfg["cnx_data"].replace(sync_prefix, async_prefix, 1)}
    return cnx_cfg


@pytest.fixture
def cnx(cnx_cfg):
    from alchemy_api import Conexion
    return Conexion(**cnx_cfg)


@pytest.fixture
def cnx_no_raise(cnx_cfg):
    from alchemy_api import Conexion
    return Conexion(**cnx_cfg, _raise=False)
