from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alchemy_api import AsyncConexion, Conexion
from alchemy_api.api_fastapi import api_db, api_log, api_log_delete, register_exception_handlers


def make_app(cnx=None, lifespan=None):
    app = FastAPI(lifespan=lifespan)
    if cnx is not None:
        app.state.cnx = cnx
    register_exception_handlers(app)
    app.include_router(api_db, prefix="/db")
    app.include_router(api_log, prefix="/log")
    app.include_router(api_log_delete, prefix="/delete_log")
    return app


@pytest.fixture
def app(cnx):
    return make_app(cnx)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def async_client(db_path):
    @asynccontextmanager
    async def lifespan(app):
        # Created inside the app event loop so aiosqlite connections stay valid
        app.state.cnx = await AsyncConexion.create(f"sqlite+aiosqlite:///{db_path}")
        yield
        await app.state.cnx._engine.dispose()

    with TestClient(make_app(lifespan=lifespan)) as client:
        yield client


@pytest.fixture(params=["sync", "async"])
def any_client(request):
    return request.getfixturevalue("client" if request.param == "sync" else "async_client")


def test_select(any_client):
    rsp = any_client.post("/db/select", json={"table": "users", "filterby": {"age": 30}, "orderby": {"id": False}})
    assert rsp.status_code == 200
    assert [r["name"] for r in rsp.json()] == ["ana", "marta"]


def test_select_count(any_client):
    rsp = any_client.post("/db/select", json={"table": "users", "count": True})
    assert list(rsp.json().values()) == [4]


def test_select_unknown_table(any_client):
    rsp = any_client.post("/db/select", json={"table": "nope"})
    assert rsp.status_code == 400
    assert "nope" in rsp.json()["error"]


def test_select_missing_table_is_validation_error(any_client):
    assert any_client.post("/db/select", json={}).status_code == 422


def test_insert_update_delete(any_client):
    rsp = any_client.post("/db/insert", json={"table": "users", "data": [{"id": 10, "name": "a", "age": 1}, {"id": 11, "name": "b", "age": 1}]})
    assert rsp.json() == {"insert": 2}
    rsp = any_client.post("/db/update", json={"table": "users", "data": {"age": 2}, "filterby": {"age": 1}})
    assert rsp.json() == {"update": 2}
    rsp = any_client.post("/db/delete", json={"table": "users", "filterby": {"age": 2}})
    assert rsp.json() == {"delete": 2}


def test_update_delete_require_filterby(any_client):
    assert any_client.post("/db/update", json={"table": "users", "data": {"age": 0}}).status_code == 422
    assert any_client.post("/db/update", json={"table": "users", "data": {"age": 0}, "filterby": {}}).status_code == 400
    assert any_client.post("/db/delete", json={"table": "users", "filterby": {}}).status_code == 400
    assert len(any_client.post("/db/select", json={"table": "users"}).json()) == 4


def test_tables_and_schema(any_client):
    assert any_client.get("/db/tables").json() == {"tables": ["users"], "views": []}
    schema = any_client.post("/db/schema", json={"table": "users"}).json()
    assert set(schema["columns"]) == {"id", "name", "age", "created"}


def test_sql_disabled_by_default(any_client):
    rsp = any_client.post("/db/sql", json={"statement": "DELETE FROM users"})
    assert rsp.status_code == 403
    assert len(any_client.post("/db/select", json={"table": "users"}).json()) == 4


def test_sql_enabled(any_client):
    any_client.app.state.allow_raw_sql = True
    rsp = any_client.post("/db/sql", json={"statement": "SELECT name FROM users WHERE id = :id", "parameters": {"id": 1}, "ret": True})
    assert rsp.json() == [{"name": "ana"}]
    rsp = any_client.post("/db/sql", json={"statement": "DELETE FROM users WHERE id = 1"})
    assert rsp.status_code == 204


def test_sql_ret_must_be_bool(any_client):
    any_client.app.state.allow_raw_sql = True
    assert any_client.post("/db/sql", json={"statement": "SELECT 1", "ret": "yes"}).status_code == 422


def test_cnx_not_configured():
    with TestClient(make_app()) as client:
        rsp = client.get("/db/tables")
    assert rsp.status_code == 500


def test_logs(db_path, tmp_path):
    cnx = Conexion(f"sqlite:///{db_path}", config_log={"log_path": tmp_path / "logs" / "log", "level_log": "DEBUG"})
    with TestClient(make_app(cnx)) as client:
        client.post("/db/select", json={"table": "users"})
        dates = client.get("/log").json()
        assert len(dates) == 1
        lines = client.get(f"/log/order/{dates[0]}").json()
        assert "Start Application" in lines[0]
        reverse = client.get(f"/log/reverse/{dates[0]}/1").json()
        assert len(reverse) == 1 and "SELECT" in reverse[0]
        assert client.get("/log/reverse/2000-01-01").status_code == 404
        # The current log can not be removed
        assert client.delete(f"/delete_log/{dates[0]}").status_code == 400
