import pytest
from flask import Flask

from alchemy_api.api_db import api_db


@pytest.fixture
def app(cnx):
    app = Flask(__name__)
    app.config["CNX"] = cnx
    app.register_blueprint(api_db, url_prefix="/db")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_select(client):
    rsp = client.post("/db/select", json={"table": "users", "filterby": {"id": 1}})
    assert rsp.status_code == 200
    assert rsp.json[0]["name"] == "ana"


def test_sql_disabled_by_default(client):
    rsp = client.post("/db/sql", json={"statement": "DELETE FROM users"})
    assert rsp.status_code == 403
    assert len(client.post("/db/select", json={"table": "users"}).json) == 4


def test_sql_enabled(app, client):
    app.config["DB_ALLOW_RAW_SQL"] = True
    rsp = client.post("/db/sql", json={"statement": "SELECT count(*) AS n FROM users", "ret": True})
    assert rsp.json == [{"n": 4}]


def test_update_requires_filterby(client):
    rsp = client.post("/db/update", json={"table": "users", "data": {"age": 0}})
    assert rsp.status_code == 400
    rsp = client.post("/db/update", json={"table": "users", "data": {"age": 0}, "filterby": {"id": 1}})
    assert rsp.json == {"update": 1}


def test_delete(client):
    rsp = client.post("/db/delete", json={"filterby": {"id": 1}})
    assert rsp.status_code == 400
    assert "table" in rsp.json["error"]
    rsp = client.post("/db/delete", json={"table": "users", "filterby": {"id": 1}})
    assert rsp.json == {"delete": 1}


def test_select_join(cnx_orders):
    app = Flask(__name__)
    app.config["CNX"] = cnx_orders
    app.register_blueprint(api_db, url_prefix="/db")
    rsp = app.test_client().post("/db/select", json={
        "table": "users", "colset": ["name", "orders.total"],
        "join": [{"table": "orders", "type": "left", "on": {"id": "user_id"}}],
        "orderby": {"id": False, "orders.id": False},
    })
    assert rsp.status_code == 200
    assert [r["orders.total"] for r in rsp.json] == [10, 20, 5, None, None]
