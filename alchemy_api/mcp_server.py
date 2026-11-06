"""MCP server over a Conexion / AsyncConexion (pip install "sqlalchemy-rest-api[mcp]")

Gives an LLM client (Claude Desktop, Claude Code, ...) the same operations as the REST api, as tools:
list_tables, describe_table, select, insert, update, delete and exec_sql.

The server runs with one role (stdio: one process per client), checked with the same "permissions"
section as the REST api. Only the tools the role can use are registered, so a role with
["tables", "schema", "select"] gets a read only server. Writes are also left out when the
connection is read_only, and exec_sql only exists with allow_raw_sql and a role with "tables": ["*"].

    from alchemy_api.mcp_server import create_mcp
    mcp = create_mcp(cnx, roles=roles, tables=tables, role="reader")
    mcp.run()  # stdio

Command line (see main): alchemy-api-mcp --config settings.json --role reader
"""
from functools import wraps
from inspect import iscoroutinefunction
import argparse
import json
import logging
from os import getenv
from pathlib import Path
from typing import Any

import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from .permissions import check_permission, check_table, filter_tables
from .utils import DbException, env_bool, read_cnx_data

_logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 1000
WRITE_OPERATIONS = ("insert", "update", "delete")

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_INSERT = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_UPDATE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)
_DELETE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)
_SQL = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

_FILTER_HELP = """filterby: {"col": value} is ==, several keys are AND.
Operators: {"col": {"type": ">", "value": 10}}, {"col": {"type": "in", "value": [1, 2]}},
{"col": {"type": "between", "value1": 1, "value2": 5}}. Types: ==, !=, <, <=, >, >=, in, not_in,
is, is_not, like, ilike, not_like, not_ilike, contains, icontains, startswith, endswith, match,
regexp_match, between. OR: [{"key": "col", "conditions": [v1, v2], "and": false}]."""


async def _call(method, *args, **kwargs):
    # AsyncConexion methods are awaited, sync ones run in a thread to not block the event loop
    if iscoroutinefunction(method):
        return await method(*args, **kwargs)
    return await anyio.to_thread.run_sync(lambda: method(*args, **kwargs))


def _rows(rows:list) -> dict:
    # One json object: a bare list would be one content block per row
    return {"rows": rows, "n_rows": len(rows)}


def _check_role(roles:dict | None, tables:dict | None, role:str | None):
    """Fail at start instead of refusing every call: permissions need a known role"""
    if roles is None and tables is None:
        return
    if role is None:
        raise ValueError("Permissions configured but no role given for the MCP server")
    for section, values in (("roles", roles), ("tables", tables)):
        if values is not None and role not in values:
            raise ValueError(f"Role {role!r} is not in the permissions ({section})")


def create_mcp(cnx, *, roles:dict=None, tables:dict=None, role:str=None, allow_raw_sql:bool=False,
               max_rows:int=DEFAULT_MAX_ROWS, name:str="sqlalchemy-rest-api") -> MCPServer:
    """MCP server with the tools the role can use.

    cnx: Conexion or AsyncConexion. roles, tables: from read_permissions (None: no control).
    role: role of the server, required when there are permissions.
    allow_raw_sql: registers exec_sql (also needs a role with every table).
    max_rows: cap for select (default limit and maximum for integer limits)"""
    _check_role(roles, tables, role)
    if max_rows < 1:
        raise ValueError("max_rows must be >= 1")
    # Constant role: the server has one identity, the check functions only need a non None get_role
    get_role = lambda: role  # noqa: E731

    def allowed(operation:str) -> bool:
        return roles is None or operation in roles[role]

    def guard(operation:str, table:str | None = ...):
        check_permission(roles, get_role, role, operation)
        if table is not ...:
            check_table(tables, get_role, role, table)

    writable = not getattr(cnx, "_read_only", False)
    registered = []
    instructions = (
        "Database tools over an existing database (SQLAlchemy reflection). "
        "Use list_tables and describe_table before select. "
        f"select returns at most {max_rows} rows: use filterby, colset, offset and count."
    )
    mcp = MCPServer(name, instructions=instructions)

    def tool(annotations:ToolAnnotations, description:str=None):
        def register(fn):
            registered.append(fn.__name__)
            return mcp.tool(description=description, annotations=annotations)(_db_errors(fn))
        return register

    if allowed("tables"):
        @tool(_READ)
        async def list_tables() -> dict:
            """Tables and views of the database that can be used"""
            guard("tables")
            tables_, views = cnx.tables()
            return {
                "tables": filter_tables(tables, get_role, role, tables_),
                "views": filter_tables(tables, get_role, role, views),
            }

    if allowed("schema"):
        @tool(_READ)
        async def describe_table(table:str) -> dict:
            """Columns (name, type, primary_key, nullable, default), indexes and foreign keys of a table"""
            guard("schema", table)
            return cnx.schema(table)

    if allowed("select"):
        @tool(_READ, description=f"""Rows of a table: {{"rows": [objects], "n_rows": n}}.
colset: columns to return (default all). orderby: {{"col": true}} descending, false ascending.
limit: rows (max {max_rows}, default {max_rows}); a value below 1 is a percentage.
count: true returns only {{"count": n}}.
{_FILTER_HELP}""")
        async def select(
            table:str,
            colset:list[str] | None = None,
            filterby:dict[str, Any] | list[dict[str, Any]] | None = None,
            orderby:dict[str, bool] | None = None,
            offset:int | None = None,
            limit:float | None = None,
            count:bool = False,
        ):
            guard("select", table)
            if limit is None or limit >= 1:
                limit = min(int(limit or max_rows), max_rows)
            result = await _call(
                cnx.select, table, colset=colset, filterby=filterby, orderby=orderby,
                offset=offset, limit=limit, count=count,
            )
            return result if count else _rows(result)

    if writable and allowed("insert"):
        @tool(_INSERT)
        async def insert(table:str, data:dict[str, Any] | list[dict[str, Any]]) -> dict:
            """Inserts one row (object) or several (list of objects). Returns the number of rows"""
            guard("insert", table)
            if not data:
                raise ToolError("data is empty")
            return {"insert": await _call(cnx.insert, table=table, data=data)}

    if writable and allowed("update"):
        @tool(_UPDATE, description="Sets the values of data in the rows matching filterby (required). "
                                   f"Returns the number of rows.\n{_FILTER_HELP}")
        async def update(table:str, data:dict[str, Any], filterby:dict[str, Any] | list[dict[str, Any]]) -> dict:
            guard("update", table)
            if not data:
                raise ToolError("data is empty")
            if not filterby:
                raise ToolError("filterby is required")
            return {"update": await _call(cnx.update, table=table, data=data, filterby=filterby)}

    if writable and allowed("delete"):
        @tool(_DELETE, description="Deletes the rows matching filterby (required). "
                                   f"Returns the number of rows.\n{_FILTER_HELP}")
        async def delete(table:str, filterby:dict[str, Any] | list[dict[str, Any]]) -> dict:
            guard("delete", table)
            if not filterby:
                raise ToolError("filterby is required")
            return {"delete": await _call(cnx.delete, table=table, filterby=filterby)}

    # Raw SQL can touch any table: only roles with "tables": ["*"]
    if writable and allow_raw_sql and allowed("sql") and (tables is None or tables[role] is None):
        @tool(_SQL)
        async def exec_sql(statement:str, parameters:dict[str, Any] | None = None, ret:bool = False):
            """Runs a raw SQL statement. Values always as bind parameters: "... WHERE id = :id" with
            parameters {"id": 1}, never inside the text. ret: true returns the rows (for SELECT)"""
            guard("sql", None)
            result = await _call(cnx.exec_sql, statement, ret=ret, bind=parameters or {})
            return _rows(result) if ret else {"ok": True}

    _logger.info("MCP server %r, role %r, tools: %s", name, role, ", ".join(registered))
    return mcp


def _db_errors(fn):
    """DbException -> ToolError: the model reads the message (status code included)"""
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except DbException as err:
            raise ToolError(f"{err} (status {getattr(err, 'status_code', None) or 500})") from None
    return wrapper


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alchemy-api-mcp",
        description="MCP server (stdio) over an existing database with sqlalchemy-rest-api",
    )
    parser.add_argument("--config", default=getenv("CONFIG_FILE"),
                        help="settings json with \"database\" and optional \"permissions\" (env CONFIG_FILE). "
                             "Without it the connection comes from DB_URI or DB_TYPE/DB_SERVER/...")
    parser.add_argument("--role", default=getenv("MCP_ROLE"), help="role of the server (env MCP_ROLE)")
    parser.add_argument("--read-only", action="store_true", default=None,
                        help="no insert/update/delete/sql tools (env READ_ONLY)")
    parser.add_argument("--allow-raw-sql", action="store_true", default=env_bool("DB_ALLOW_RAW_SQL"),
                        help="adds the exec_sql tool (env DB_ALLOW_RAW_SQL)")
    parser.add_argument("--max-rows", type=int, default=int(getenv("MCP_MAX_ROWS", DEFAULT_MAX_ROWS)),
                        help=f"maximum rows per select (env MCP_MAX_ROWS, default {DEFAULT_MAX_ROWS})")
    parser.add_argument("--name", default="sqlalchemy-rest-api", help="server name")
    return parser


def main(argv:list[str] | None = None):
    from .conexion import Conexion
    from .permissions import read_permissions

    args = _parser().parse_args(argv)
    settings = {}
    if args.config:
        config = Path(args.config).expanduser()
        if not config.is_file():
            raise SystemExit(f"Settings file not found: {config}")
        with open(config) as f:
            settings = json.load(f)
    cnx_data, cnx_data_extra, _show_query, modifiers, config_log = read_cnx_data(dict(settings.get("database", {})))
    roles, tables = read_permissions(settings.get("permissions"))
    # show_query prints to stdout, which is the stdio transport of MCP: always off here
    cnx = Conexion(cnx_data, cnx_data_extra=cnx_data_extra, modifiers=modifiers,
                   config_log=config_log, read_only=args.read_only)
    try:
        mcp = create_mcp(cnx, roles=roles, tables=tables, role=args.role,
                         allow_raw_sql=args.allow_raw_sql, max_rows=args.max_rows, name=args.name)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    try:
        mcp.run("stdio")
    finally:
        cnx._engine.dispose()


if __name__ == "__main__":
    main()
