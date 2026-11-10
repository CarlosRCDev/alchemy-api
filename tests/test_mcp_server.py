import asyncio
import json

import pytest

from alchemy_api import AsyncConexion, Conexion

pytest.importorskip("mcp")
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

from alchemy_api.mcp_server import create_mcp, http_app, main  # noqa: E402
from alchemy_api.permissions import read_permissions  # noqa: E402

TOKEN = "t" * 32
READ_TOOLS = ["my_permissions", "list_tables", "describe_table", "select"]
WRITE_TOOLS = ["insert", "update", "delete"]


def run(coro):
    return asyncio.run(coro)


def tool_names(mcp) -> list[str]:
    return [tool.name for tool in run(mcp.list_tools())]


async def _acall(mcp, name:str, **arguments):
    result = await mcp.call_tool(name, arguments)
    assert not result.is_error, result.content
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


def call(mcp, name:str, **arguments):
    return run(_acall(mcp, name, **arguments))


def test_tools_without_permissions(cnx):
    assert tool_names(create_mcp(cnx)) == READ_TOOLS + WRITE_TOOLS
    assert tool_names(create_mcp(cnx, allow_raw_sql=True)) == READ_TOOLS + WRITE_TOOLS + ["exec_sql"]


def test_tools_by_role(cnx, roles, tables):
    assert tool_names(create_mcp(cnx, roles=roles, tables=tables, role="reader", allow_raw_sql=True)) == READ_TOOLS
    # editor has every table operation but only "users": no raw SQL
    assert tool_names(create_mcp(cnx, roles=roles, tables=tables, role="editor", allow_raw_sql=True)) == READ_TOOLS + WRITE_TOOLS
    assert tool_names(create_mcp(cnx, roles=roles, tables=tables, role="admin", allow_raw_sql=True)) == READ_TOOLS + WRITE_TOOLS + ["exec_sql"]


def test_read_only_connection_has_no_write_tools(cnx_cfg, roles, tables):
    cnx = Conexion(**cnx_cfg, read_only=True)
    assert tool_names(create_mcp(cnx, roles=roles, tables=tables, role="admin", allow_raw_sql=True)) == READ_TOOLS


def test_role_required_with_permissions(cnx, roles, tables):
    with pytest.raises(ValueError, match="no role"):
        create_mcp(cnx, roles=roles, tables=tables)
    with pytest.raises(ValueError, match="nope"):
        create_mcp(cnx, roles=roles, tables=tables, role="nope")


def test_list_tables_and_describe(cnx):
    mcp = create_mcp(cnx)
    assert call(mcp, "list_tables") == {"tables": ["users"], "views": []}
    schema = call(mcp, "describe_table", table="users")
    columns = {col["name"].lower(): col for col in schema["columns"]}
    assert set(columns) == {"id", "name", "age", "created"}
    assert columns["id"]["primary_key"] is True
    assert columns["name"]["primary_key"] is False
    assert isinstance(columns["name"]["nullable"], bool)
    assert "CHAR" in columns["name"]["type"].upper()
    assert isinstance(schema["indexes"], list)
    assert schema["foreign_keys"] == []


def test_select(cnx):
    mcp = create_mcp(cnx)
    result = call(mcp, "select", table="users", filterby={"age": 30}, orderby={"id": False})
    assert [row["name"] for row in result["rows"]] == ["ana", "marta"]
    assert result["n_rows"] == 2
    assert list(call(mcp, "select", table="users", count=True).values()) == [4]


def test_select_max_rows(cnx):
    mcp = create_mcp(cnx, max_rows=2)
    assert call(mcp, "select", table="users", orderby={"id": False})["n_rows"] == 2
    assert call(mcp, "select", table="users", limit=100)["n_rows"] == 2
    assert call(mcp, "select", table="users", limit=1)["n_rows"] == 1
    # count is not limited
    assert list(call(mcp, "select", table="users", count=True).values()) == [4]


def test_insert_update_delete(cnx):
    mcp = create_mcp(cnx)
    assert call(mcp, "insert", table="users", data=[{"id": 10, "name": "a", "age": 1}, {"id": 11, "name": "b", "age": 1}]) == {"insert": 2}
    assert call(mcp, "update", table="users", data={"age": 2}, filterby={"age": 1}) == {"update": 2}
    assert call(mcp, "delete", table="users", filterby={"age": 2}) == {"delete": 2}


def test_update_delete_require_filterby(cnx):
    mcp = create_mcp(cnx)
    with pytest.raises(ToolError, match="filterby"):
        run(mcp.call_tool("delete", {"table": "users", "filterby": {}}))
    with pytest.raises(ToolError, match="filterby"):
        run(mcp.call_tool("update", {"table": "users", "data": {"age": 0}, "filterby": {}}))
    assert call(mcp, "select", table="users")["n_rows"] == 4


def test_db_error_is_tool_error(cnx):
    with pytest.raises(ToolError, match="status 400"):
        run(create_mcp(cnx).call_tool("select", {"table": "nope"}))


def test_table_permissions(cnx, roles, tables):
    mcp = create_mcp(cnx, roles=roles, tables={**tables, "reader": frozenset({"other"})}, role="reader")
    assert call(mcp, "list_tables") == {"tables": [], "views": []}
    with pytest.raises(ToolError, match="status 403"):
        run(mcp.call_tool("select", {"table": "users"}))


def test_exec_sql_bind(cnx):
    mcp = create_mcp(cnx, allow_raw_sql=True)
    result = call(mcp, "exec_sql", statement="SELECT name FROM users WHERE id = :id", parameters={"id": 2}, ret=True)
    assert [list(row.values()) for row in result["rows"]] == [["luis"]]


def test_async_conexion(async_db_cfg):
    async def main():
        cnx = await AsyncConexion.create(**async_db_cfg)
        try:
            mcp = create_mcp(cnx)
            rows = (await _acall(mcp, "select", table="users", filterby={"age": 30}, orderby={"id": False}))["rows"]
            inserted = await _acall(mcp, "insert", table="users", data={"id": 20, "name": "z", "age": 9})
            deleted = await _acall(mcp, "delete", table="users", filterby={"id": 20})
            return [row["name"] for row in rows], inserted, deleted
        finally:
            await cnx._engine.dispose()
    assert run(main()) == (["ana", "marta"], {"insert": 1}, {"delete": 1})


def test_main_fails_without_role(tmp_path, settings_json, db_cfg):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(settings_json))
    with pytest.raises(SystemExit, match="no role"):
        main(["--config", str(config)])


def test_main_http_needs_token(tmp_path, settings_json, monkeypatch):
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(settings_json))
    with pytest.raises(SystemExit, match="MCP_TOKEN"):
        main(["--config", str(config), "--role", "reader", "--transport", "http"])


@pytest.mark.parametrize("token", [None, "", "short"])
def test_http_refuses_weak_token(cnx, token):
    with pytest.raises(ValueError, match="MCP_TOKEN"):
        http_app(create_mcp(cnx), token)


def _rpc(client:TestClient, method:str, params:dict=None, token:str=TOKEN):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=headers)


def test_http_auth_and_tools(cnx):
    app = http_app(create_mcp(cnx), TOKEN, host="0.0.0.0")
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert _rpc(client, "tools/list", token=None).status_code == 401
        assert _rpc(client, "tools/list", token="x" * 32).status_code == 401
        initialize = _rpc(client, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })
        assert initialize.status_code == 200, initialize.text
        tools = _rpc(client, "tools/list")
        assert tools.status_code == 200, tools.text
        assert {tool["name"] for tool in tools.json()["result"]["tools"]} >= set(READ_TOOLS)


def test_my_permissions(cnx):
    assert call(create_mcp(cnx), "my_permissions")["role"] is None
    roles, tables = read_permissions({"reader": {"roles": ["tables", "select"], "tables": ["users"]}})
    result = call(create_mcp(cnx, roles=roles, tables=tables, role="reader"), "my_permissions")
    assert result == {"role": "reader", "operations": ["select", "tables"], "tables": ["users"]}



def test_select_join(cnx_orders, roles, tables):
    join = [{"table": "orders", "type": "inner", "on": {"id": "user_id"}}]
    result = call(create_mcp(cnx_orders), "select", table="users", colset=["name", "orders.total"], join=join, orderby={"orders.id": False})
    assert result == {"rows": [{"name": "ana", "orders.total": 10}, {"name": "ana", "orders.total": 20}, {"name": "luis", "orders.total": 5}], "n_rows": 3}
    # Joined tables need the table permission too
    mcp = create_mcp(cnx_orders, roles=roles, tables={**tables, "reader": frozenset({"users"})}, role="reader")
    with pytest.raises(ToolError, match="status 403"):
        run(mcp.call_tool("select", {"table": "users", "join": join}))
