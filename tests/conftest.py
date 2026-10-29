import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

# The package folder is "alchemy-api" (not importable), load it as "alchemy_api"
PKG_DIR = Path(__file__).resolve().parent.parent / "alchemy-api"
_spec = importlib.util.spec_from_file_location(
    "alchemy_api", PKG_DIR / "__init__.py", submodule_search_locations=[str(PKG_DIR)]
)
alchemy_api = importlib.util.module_from_spec(_spec)
sys.modules["alchemy_api"] = alchemy_api
_spec.loader.exec_module(alchemy_api)

ROWS = [
    {"id": 1, "name": "ana", "age": 30},
    {"id": 2, "name": "luis", "age": 25},
    {"id": 3, "name": "marta", "age": 30},
    {"id": 4, "name": "pepa", "age": 40},
]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(50), age INTEGER, created DATETIME)"
        ))
        conn.execute(text("INSERT INTO users (id, name, age) VALUES (:id, :name, :age)"), ROWS)
    engine.dispose()
    return path


@pytest.fixture
def cnx(db_path):
    from alchemy_api import Conexion
    return Conexion(f"sqlite:///{db_path}")


@pytest.fixture
def cnx_no_raise(db_path):
    from alchemy_api import Conexion
    return Conexion(f"sqlite:///{db_path}", _raise=False)
