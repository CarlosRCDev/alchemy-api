import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from alchemy_api import Conexion
from alchemy_api import api_db as flask_api
from alchemy_api import api_fastapi as fastapi_api
from alchemy_api.permissions import OPERATIONS, read_permissions, read_roles, read_tables, table_allowed
from alchemy_api.utils import DbException

# One request per operation; ids differ so repeated inserts don't collide
REQUESTS = {
    "tables": lambda i: ("get", "/db/tables", None),
    "schema": lambda i: ("post", "/db/schema", {"table": "users"}),
    "select": lambda i: ("post", "/db/select", {"table": "users"}),
    "insert": lambda i: ("post", "/db/insert", {"table": "users", "data": [{"id": 100 + i, "name": "x", "age": 1}]}),
    "update": lambda i: ("post", "/db/update", {"table": "users", "data": {"age": 2}, "filterby": {"id": 1}}),
    "delete": lambda i: ("post", "/db/delete", {"table": "users", "filterby": {"id": 100 + i}}),
    "sql": lambda i: ("post", "/db/sql", {"statement": "SELECT id FROM users", "ret": True}),
    "log_read": lambda i: ("get", "/log", None),
    "log_delete": lambda i: ("delete", "/delete_log/2000-01-01", None),
}


def get_role(request):
    # Tests only: a real app must validate a token, not trust a header
    return request.headers.get("X-Role")


def flask_client(cnx, roles, with_get_role=True, tables=None):
    app = Flask(__name__)
    app.config.update(CNX=cnx, DB_ALLOW_RAW_SQL=True, DB_ROLES=roles, DB_TABLES=tables)
    if with_get_role:
        app.config["DB_GET_ROLE"] = get_role
    app.register_blueprint(flask_api.api_db, url_prefix="/db")
    app.register_blueprint(flask_api.api_log, url_prefix="/log")
    app.register_blueprint(flask_api.api_log_delete, url_prefix="/delete_log")
    return app.test_client()


def fastapi_client(cnx, roles, with_get_role=True, tables=None):
    app = FastAPI()
    app.state.cnx = cnx
    app.state.allow_raw_sql = True
    app.state.roles = roles
    app.state.tables = tables
    if with_get_role:
        app.state.get_role = get_role
    fastapi_api.register_exception_handlers(app)
    app.include_router(fastapi_api.api_db, prefix="/db")
    app.include_router(fastapi_api.api_log, prefix="/log")
    app.include_router(fastapi_api.api_log_delete, prefix="/delete_log")
    return TestClient(app)


def call(client, operation, role, i=0):
    method, url, body = REQUESTS[operation](i)
    headers = {"X-Role": role} if role else {}
    if body is None:
        return getattr(client, method)(url, headers=headers)
    return getattr(client, method)(url, json=body, headers=headers)


@pytest.fixture(params=["flask", "fastapi"])
def make_client(request):
    return flask_client if request.param == "flask" else fastapi_client


def test_requests_cover_all_operations():
    assert set(REQUESTS) == OPERATIONS


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_roles_from_settings(make_client, cnx, roles, tables, operation):
    if roles is None:
        pytest.skip("No roles in the settings file")
    # The settings give every role the users table, so only the operation decides
    client = make_client(cnx, roles, tables=tables)
    for i, (role, allowed) in enumerate(roles.items()):
        status = call(client, operation, role, i).status_code
        if operation in allowed:
            assert status not in (401, 403), (role, operation, status)
        else:
            assert status == 403, (role, operation, status)


def test_without_role_or_unknown_role(make_client, cnx, roles):
    if roles is None:
        pytest.skip("No roles in the settings file")
    client = make_client(cnx, roles)
    assert call(client, "select", None).status_code == 401
    assert call(client, "select", "nobody").status_code == 403


def test_roles_without_get_role_are_refused(make_client, cnx, roles):
    if roles is None:
        pytest.skip("No roles in the settings file")
    client = make_client(cnx, roles, with_get_role=False)
    assert call(client, "select", "admin").status_code == 500


def test_without_roles_everything_is_allowed(make_client, cnx):
    client = make_client(cnx, None)
    for operation in OPERATIONS:
        assert call(client, operation, None).status_code not in (401, 403, 500), operation


def test_read_roles():
    assert read_roles(None) is None
    assert read_roles({}) is None
    roles = read_roles({"admin": ["*"], "reader": ["select"], "one": "tables"})
    assert roles == {"admin": OPERATIONS, "reader": {"select"}, "one": {"tables"}}
    with pytest.raises(ValueError, match="selec"):
        read_roles({"reader": ["selec"]})


def test_read_permissions():
    assert read_permissions(None) == (None, None)
    assert read_permissions({}) == (None, None)
    roles, tables = read_permissions({
        "admin": {"roles": ["*"], "tables": ["*"]},
        "reader": {"roles": ["select"], "tables": ["Users"]},
    })
    assert roles == {"admin": OPERATIONS, "reader": {"select"}}
    assert tables == {"admin": None, "reader": {"users"}}
    # Only operations: no table control
    assert read_permissions({"reader": {"roles": ["select"]}}) == ({"reader": {"select"}}, None)
    # Only tables: no operation control
    assert read_permissions({"reader": {"tables": ["users"]}}) == (None, {"reader": {"users"}})
    # A role without a key used by others gets nothing
    roles, tables = read_permissions({"admin": {"roles": ["*"], "tables": ["*"]}, "other": {"roles": ["select"]}})
    assert tables["other"] == frozenset() and not table_allowed(tables, "other", "users")


@pytest.mark.parametrize("wrong", [{"r": ["select"]}, {"r": {"role": ["select"]}}, {"r": {"roles": ["selec"]}}, {"r": {"tables": [1]}}])
def test_read_permissions_invalid(wrong):
    with pytest.raises(ValueError):
        read_permissions(wrong)


TABLE_OPERATIONS = ("schema", "select", "insert", "update", "delete")
TABLES = {"admin": ["*"], "users_role": ["USERS"], "data": ["data", "other"]}


def test_read_tables():
    assert read_tables(None) is None
    assert read_tables({}) is None
    tables = read_tables({"admin": ["*"], "one": "Users", "two": ["users", "data"]})
    assert tables == {"admin": None, "one": {"users"}, "two": {"users", "data"}}
    for wrong in ({"r": 1}, {"r": [""]}, {"r": [1]}):
        with pytest.raises(ValueError):
            read_tables(wrong)


def test_table_allowed():
    tables = read_tables(TABLES)
    assert table_allowed(None, None, "x")
    assert table_allowed(tables, "admin", "anything")
    assert table_allowed(tables, "admin", None)
    assert table_allowed(tables, "users_role", "users")
    assert not table_allowed(tables, "users_role", "data")
    assert not table_allowed(tables, "users_role", None)
    assert not table_allowed(tables, "nobody", "users")


@pytest.mark.parametrize("operation", TABLE_OPERATIONS)
def test_tables_by_role(make_client, cnx, operation):
    client = make_client(cnx, None, tables=read_tables(TABLES))
    for i, role in enumerate(("admin", "users_role")):
        status = call(client, operation, role, i).status_code
        assert status not in (401, 403, 500), (role, operation, status)
    assert call(client, operation, "data", 5).status_code == 403
    assert call(client, operation, "nobody", 6).status_code == 403
    assert call(client, operation, None, 7).status_code == 401


def test_tables_list_is_filtered(make_client, cnx):
    client = make_client(cnx, None, tables=read_tables(TABLES))
    for role, expected in (("admin", True), ("users_role", True), ("data", False)):
        response = call(client, "tables", role)
        # Flask: .json property, FastAPI (httpx): .json() method
        body = response.json() if callable(response.json) else response.json
        assert ("users" in [t.lower() for t in body["tables"]]) is expected, role
    assert call(client, "tables", None).status_code == 401


def test_tables_sql_needs_every_table(make_client, cnx):
    client = make_client(cnx, None, tables=read_tables(TABLES))
    assert call(client, "sql", "admin").status_code == 200
    assert call(client, "sql", "users_role").status_code == 403


def test_tables_with_roles(make_client, cnx, roles):
    if roles is None:
        pytest.skip("No roles in the settings file")
    # editor may select but only on its tables; reader has the table but not insert
    tables = read_tables({"editor": ["data"], "reader": ["users"]})
    client = make_client(cnx, roles, tables=tables)
    assert call(client, "select", "editor").status_code == 403
    assert call(client, "select", "reader").status_code == 200
    assert call(client, "insert", "reader").status_code == 403
    # admin has every operation but is not in "tables": refused
    assert call(client, "select", "admin").status_code == 403


def test_tables_without_get_role_are_refused(make_client, cnx):
    client = make_client(cnx, None, with_get_role=False, tables=read_tables(TABLES))
    assert call(client, "select", "admin").status_code == 500
    assert call(client, "tables", "admin").status_code == 500


def test_read_only_conexion(cnx_cfg):
    cnx = Conexion(**cnx_cfg, read_only=True)
    assert len(cnx.select("users")) == 4
    for method, args in (
        (cnx.insert, ("users", {"id": 99, "name": "x", "age": 1})),
        (cnx.update, ("users", {"age": 0})),
        (cnx.delete, ("users", {"id": 1})),
        (cnx.exec_sql, ("DELETE FROM users",)),
    ):
        with pytest.raises(DbException) as exc:
            method(*args)
        assert exc.value.status_code == 403
    assert len(cnx.select("users")) == 4


@pytest.mark.parametrize("value, expected", [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("", False)])
def test_read_only_env_var(cnx_cfg, monkeypatch, value, expected):
    monkeypatch.setenv("READ_ONLY", value)
    assert Conexion(**cnx_cfg)._read_only is expected


def test_read_only_argument_overrides_env_var(cnx_cfg, monkeypatch):
    monkeypatch.setenv("READ_ONLY", "true")
    cnx = Conexion(**cnx_cfg, read_only=False)
    assert cnx.update("users", {"age": 31}, filterby={"id": 1}) == 1


def test_read_only_env_var_invalid(cnx_cfg, monkeypatch):
    monkeypatch.setenv("READ_ONLY", "maybe")
    with pytest.raises(ValueError, match="READ_ONLY"):
        Conexion(**cnx_cfg)


def test_read_only_env_var_unset(cnx_cfg, monkeypatch):
    monkeypatch.delenv("READ_ONLY", raising=False)
    assert Conexion(**cnx_cfg)._read_only is False
