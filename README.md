# sqlalchemy-rest-api

CRUD with python dicts and an automatic REST api (Flask or FastAPI) over **existing databases**.
Tables are read with SQLAlchemy reflection: no models to write.

- `select`, `insert`, `update`, `delete`, `exec_sql` with plain dicts and lists
- Filters with operators (`>`, `in`, `between`, `like`, `startswith`, ...) and `or` groups
- Sync (`Conexion`) and async (`AsyncConexion`) classes
- Ready-made routes for Flask (blueprints) and FastAPI (routers)
- MCP server for LLM clients (Claude Desktop, Claude Code...), with the same role permissions
- Daily rotated file log, readable through the api
- Oracle friendly: modifiers for upper/lower case tables and columns

## Install

```bash
pip install sqlalchemy-rest-api            # core
pip install "sqlalchemy-rest-api[flask]"   # + Flask api
pip install "sqlalchemy-rest-api[fastapi]" # + FastAPI api and uvicorn server
pip install "sqlalchemy-rest-api[async]"   # + AsyncConexion (includes aiosqlite for async sqlite)
pip install "sqlalchemy-rest-api[jwt]"     # + PyJWT for the JWT authentication example
pip install "sqlalchemy-rest-api[mcp]"     # + MCP server (alchemy-api-mcp command)
pip install "sqlalchemy-rest-api[all]"     # everything: apis, async, JWT, MCP and all database drivers
```

Database drivers, each one with its sync and async driver (async also needs `[async]`):

| Extra | Drivers | `type` in the settings json |
|---|---|---|
| `[oracle]` | `oracledb` | `oracle` |
| `[mariadb]` | `pymysql`, `aiomysql` | `mariadb`, `async_mariadb` |
| `[mysql]` | `pymysql`, `aiomysql` (same drivers, MySQL dialect, `utf8mb4`) | `mysql`, `async_mysql` |
| `[mssql]` | `pymssql` (sync only, no system ODBC driver needed) | `mssql` |
| `[postgres]` | `psycopg[binary]` (no system `libpq` needed) | `psycopg` |
| none | sqlite is built in (`aiosqlite` comes with `[async]`) | `sqlite` |

SQL Server notes: `select` with `offset` and no `orderby` is ordered by the primary key (SQL Server
needs `ORDER BY` for `OFFSET`). `AsyncConexion` needs `mssql+aioodbc://` through `uri`
(`aioodbc` plus Microsoft's ODBC driver on the system); that path is not tested or bundled.
Use `NVARCHAR` columns for text outside the column collation (e.g. emojis).

```bash
pip install "sqlalchemy-rest-api[fastapi,async,postgres]"   # e.g. async FastAPI over PostgreSQL
```

The package is imported as `alchemy_api`.

## Usage with a dict

```python
from alchemy_api import Conexion
from alchemy_api.utils import read_cnx_data

config = {
    "type": "sqlite",  # oracle, mariadb, async_mariadb, mysql, async_mysql, mssql, psycopg, sqlite
    "path": "example.db",
    "show_query": False,
    "log": {"path": "logdb/example.log", "level_log": "DEBUG", "backup_count": 10},
}
cnx_data, cnx_data_extra, show_query, modifiers, config_log = read_cnx_data(config)
cnx = Conexion(cnx_data, cnx_data_extra=cnx_data_extra, show_query=show_query,
               modifiers=modifiers, config_log=config_log)

cnx.tables()                                   # (["users"], [])
cnx.select("users", filterby={"age": 30}, orderby={"name": False})
cnx.select("users", colset=["name"], filterby={"age": {"type": ">", "value": 26}})
cnx.select("users", count=True)                # {"count": 3}
cnx.insert("users", [{"id": 10, "name": "pepa", "age": 40}])
cnx.update("users", {"age": 41}, filterby={"id": 10})  # 1 (rows)
cnx.delete("users", filterby={"id": 10})  # 1 (rows)
cnx.exec_sql("SELECT name FROM users WHERE age = :age", ret=True, bind={"age": 25})
```

A plain SQLAlchemy url also works: `Conexion("sqlite:///example.db")`.

`show_query` (or the `DB_SHOW_QUERY` environment variable) prints every executed statement to the console
(stdout, e.g. `docker logs`). The `log` file only gets the statements with `"level_log": "DEBUG"`;
with `INFO` it only has the start line and the errors.

Instead of `type` and its keys, the settings can give the SQLAlchemy url directly with `uri`
(or the `DB_URI` environment variable when the settings have neither `uri` nor `type`).
`uri` wins over `type`; `show_query`, `modifiers`, `cnx_data_extra` and `log` work the same:

```json
{
    "database": {
        "uri": "postgresql+psycopg://user:password@host:5432/database",
        "show_query": true,
        "modifiers": {"lower_table": true, "lower_cols": true},
        "log": {"path": "logdb/app.log", "level_log": "DEBUG", "backup_count": 10}
    }
}
```

The url goes to SQLAlchemy as is, so pick the driver in it (`postgresql+psycopg://`,
`mariadb+pymysql://`, `mysql+pymysql://`, `mssql+pymssql://`, `oracle+oracledb://`, `sqlite:///path.db`; async drivers for
`AsyncConexion`) and URL-encode special characters in the password (`@` -> `%40`).
A plain `postgresql://` uses psycopg2, which is not one of the extras.

### Filters

```python
filterby = {"age": 30}                                        # ==
filterby = {"age": {"type": "between", "value1": 26, "value2": 35}}
filterby = {"name": {"type": "in", "value": ["ana", "luis"]}}
filterby = [{"key": "name", "conditions": ["ana", "pepa"], "and": False}]  # OR
```

Types: `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not_in`, `is`, `is_not`, `like`, `ilike`,
`not_like`, `not_ilike`, `contains`, `icontains`, `startswith`, `endswith`, `match`,
`regexp_match`, `between`.

`orderby={"col": True}` is descending, `False` ascending.

## REST api with Flask

```python
from flask import Flask
from alchemy_api import Conexion
from alchemy_api.api_db import api_db, api_log, api_log_delete

app = Flask(__name__)
app.config["CNX"] = Conexion("sqlite:///example.db")
app.config["DB_ALLOW_RAW_SQL"] = False  # /db/sql disabled by default
app.register_blueprint(api_db, url_prefix="/db")
app.register_blueprint(api_log, url_prefix="/log")
app.register_blueprint(api_log_delete, url_prefix="/delete_log")
```

## REST api with FastAPI

```python
from fastapi import FastAPI
from alchemy_api import Conexion
from alchemy_api.api_fastapi import api_db, api_log, api_log_delete, register_exception_handlers

app = FastAPI()
app.state.cnx = Conexion("sqlite:///example.db")  # or await AsyncConexion.create(...)
app.state.allow_raw_sql = False
register_exception_handlers(app)
app.include_router(api_db, prefix="/db")
app.include_router(api_log, prefix="/log")
app.include_router(api_log_delete, prefix="/delete_log")
```

### Endpoints

| Method | Path | Body | Operation |
|---|---|---|---|
| GET | `/db/tables` | | `tables` |
| POST | `/db/schema` | `{"table": "users"}` | `schema` |
| POST | `/db/select` | `{"table": "users", "filterby": {...}, "orderby": {...}, "colset": [...]}` | `select` |
| POST | `/db/insert` | `{"table": "users", "data": [{...}]}` | `insert` |
| POST | `/db/update` | `{"table": "users", "data": {...}, "filterby": {...}}` | `update` |
| POST | `/db/delete` | `{"table": "users", "filterby": {...}}` | `delete` |
| POST | `/db/sql` | `{"statement": "...", "parameters": {...}, "ret": true}` (only if enabled) | `sql` |
| GET | `/log` | list of log dates | `log_read` |
| GET | `/log/order/{date}` | log lines | `log_read` |
| GET | `/log/reverse/{date}/{n_line}` | last lines first | `log_read` |
| DELETE | `/delete_log/{date}` | removes an old log | `log_delete` |

`/db/schema` (and `Conexion.schema`) returns the table structure. Column and table names follow the
`ret_upper_cols` and `ret_upper_table` modifiers:

```json
{
  "columns": [{"name": "id", "type": "INTEGER", "primary_key": true, "nullable": false, "default": null}],
  "indexes": [{"name": "ix_orders_user_id", "columns": ["user_id"], "unique": false}],
  "foreign_keys": [{"column": "user_id", "references": "users.id"}]
}
```

### Permissions

Permissions are defined per role in the `"permissions"` section of the settings json, next to `"database"`.
`"roles"` lists the operations of the role (see the table above) and `"tables"` the tables it can use.
`"*"` allows every operation / every table; table names are compared case insensitive:

```json
{
    "database": {"type": "sqlite", "path": "example.db"},
    "permissions": {
        "admin": {"roles": ["*"], "tables": ["*"]},
        "editor": {
            "roles": ["tables", "schema", "select", "insert", "update", "delete", "log_read"],
            "tables": ["users"]
        },
        "reader": {"roles": ["tables", "schema", "select"], "tables": ["users", "data"]}
    }
}
```

The library does not authenticate: the app gives a `get_role(request)` function that returns the role
of the request (from a JWT, an api key, a session...) or `None`.

```python
from alchemy_api.permissions import read_permissions

# ValueError on unknown operations, unknown keys or invalid table lists
roles, tables = read_permissions(settings.get("permissions"))

def get_role(request):
    return validate_token(request.headers.get("Authorization"))  # "admin", "reader", ... or None

# Flask
app.config["DB_ROLES"] = roles
app.config["DB_TABLES"] = tables
app.config["DB_GET_ROLE"] = get_role
# FastAPI (get_role can also be async)
app.state.roles = roles
app.state.tables = tables
app.state.get_role = get_role
```

`roles` and `tables` are two independent controls: a request needs the operation **and** the table.
If no role has a `"roles"` key there is no operation control (`roles` is `None`); the same for `"tables"`.
When a key is used by some role, a role without it gets nothing for that control.

| Situation | Response |
|---|---|
| No `permissions` configured | everything allowed (no control) |
| `get_role` returns `None` | 401 |
| Role unknown or without the operation | 403 |
| `schema`, `select`, `insert`, `update`, `delete` on a table not listed for the role | 403 |
| `GET /db/tables` | only the tables and views the role can use |
| `POST /db/sql` with table control | only roles with `"tables": ["*"]` (raw SQL can touch any table), otherwise 403 |
| Permissions configured but no `get_role` | 500 (refused, never open by mistake) |

For use without api, `Conexion(..., read_only=True)` refuses `insert`, `update`, `delete` and `exec_sql` (403).
Without the argument it is read from the `READ_ONLY` environment variable (`true`/`1`/`yes`/`on`, default off);
an explicit `read_only=True/False` wins over the variable.
For real protection also give read only roles a database user with only `SELECT` grants.

## MCP server

`alchemy-api-mcp` runs an [MCP](https://modelcontextprotocol.io) server (stdio or streamable HTTP) so an LLM client
can query and edit the database with the same operations and permissions as the REST api:

| Tool | Operation | Notes |
|---|---|---|
| `list_tables` | `tables` | only the tables and views the role can use |
| `describe_table` | `schema` | `{"columns": [{name, type, primary_key, nullable, default}], "indexes": [...], "foreign_keys": [...]}` |
| `select` | `select` | `{"rows": [...], "n_rows": n}`, at most `--max-rows` rows (default 1000) |
| `insert` | `insert` | |
| `update` | `update` | `filterby` required |
| `delete` | `delete` | `filterby` required |
| `exec_sql` | `sql` | only with `--allow-raw-sql` and a role with `"tables": ["*"]`; bind parameters |

The server runs with **one role**, from the `"permissions"` section of the settings json (same format
as [Permissions](#permissions)), and only registers the tools that role can use. A role with
`["tables", "schema", "select"]` gets a read only server: the model never sees the write tools.
Writes are also left out with `--read-only` (or `READ_ONLY`). With permissions configured, a missing
or unknown role stops the server at start (fail closed).

```bash
alchemy-api-mcp --config settings.json --role reader
```

| Option | Env var | Default |
|---|---|---|
| `--config` | `CONFIG_FILE` | none: connection from `DB_URI` or `DB_TYPE`/`DB_SERVER`/... |
| `--role` | `MCP_ROLE` | none (required when there are permissions) |
| `--read-only` | `READ_ONLY` | off |
| `--allow-raw-sql` | `DB_ALLOW_RAW_SQL` | off |
| `--max-rows` | `MCP_MAX_ROWS` | 1000 (integer limits are capped; a `limit` below 1 is still a percentage) |
| `--transport` | `MCP_TRANSPORT` | `stdio`; `http` serves streamable HTTP on `/mcp` |
| `--host` | `MCP_HOST` | `127.0.0.1` (http) |
| `--port` | `MCP_PORT` | `8001` (http) |
| | `MCP_TOKEN` | required with `http`, at least 32 characters; only from the environment |

`show_query` is always off in the command: it prints to stdout, which carries the stdio protocol.

Claude Code (`.mcp.json`) or Claude Desktop (`claude_desktop_config.json`):

```json
{
    "mcpServers": {
        "my-db": {
            "command": "uvx",
            "args": ["--from", "sqlalchemy-rest-api[mcp,postgres]", "alchemy-api-mcp",
                     "--config", "/path/settings.json", "--role", "reader"]
        }
    }
}
```

With `--transport http` the server listens on a port and refuses to start without `MCP_TOKEN`. Every request
needs `Authorization: Bearer <token>`, except `GET /health`. There is one token and one role per process: run one
server per role. The traffic is plain HTTP, so put TLS in front of it outside localhost.

```bash
export MCP_TOKEN="$(openssl rand -hex 32)"
alchemy-api-mcp --config settings.json --role reader --transport http
```

```json
{
    "mcpServers": {
        "my-db": {
            "type": "http",
            "url": "http://127.0.0.1:8001/mcp",
            "headers": {"Authorization": "Bearer ${MCP_TOKEN}"}
        }
    }
}
```

From python, with a `Conexion` or `AsyncConexion`:

```python
from alchemy_api.mcp_server import create_mcp

mcp = create_mcp(cnx, roles=roles, tables=tables, role="editor", max_rows=500)
mcp.run()  # stdio
```

An LLM with write access can still do damage within its role: prefer a read only role (and a database
user with only `SELECT` grants) unless writes are needed.

## Docker

The `deployments/` folder has an image that serves the REST api (FastAPI + uvicorn).
Build it from the repository root:

```bash
docker build -f deployments/Dockerfile -t sqlalchemy-rest-api .
```

By default it includes every database driver. To include only some of them, pass the
extras of `pyproject.toml` (comma separated) with `EXTRAS`; `fastapi` is always added:

```bash
# Only PostgreSQL (sync and async)
docker build -f deployments/Dockerfile --build-arg EXTRAS=postgres,async -t sqlalchemy-rest-api:postgres .
# Only sqlite (built in Python): no extra drivers
docker build -f deployments/Dockerfile --build-arg EXTRAS= -t sqlalchemy-rest-api:sqlite .
```

| Extra | Database |
|---|---|
| `postgres` | PostgreSQL |
| `mariadb` / `mysql` | MariaDB / MySQL |
| `mssql` | SQL Server |
| `oracle` | Oracle |
| `async` | async drivers support (greenlet, aiosqlite) |
| `jwt` | PyJWT with crypto, for `example/api_fastapi_jwt.py` (not a database driver) |

An unknown extra makes the build fail.

`deployments/build.sh` builds one image per driver, all of them with async support:
`all`, `sqlite` (no extra drivers), `postgres`, `mysql` (also valid for MariaDB), `mssql` and `oracle`.
Each one is tagged `<variant>` and `<version>-<variant>` (`all` also `latest` and `<version>`):

```bash
deployments/build.sh                                            # every variant, local only
deployments/build.sh postgres sqlite                            # some variants
IMAGE=user/sqlalchemy-rest-api deployments/build.sh --push      # build and push to Docker Hub (after docker login)
IMAGE=user/sqlalchemy-rest-api PLATFORMS=linux/amd64,linux/arm64 deployments/build.sh --push  # amd64 + arm64
```

`deployments/push.sh` only pushes images already built by `build.sh` (same `IMAGE`, `VERSION` and `LATEST`).
It checks that every tag exists locally before pushing anything:

```bash
IMAGE=user/sqlalchemy-rest-api deployments/build.sh            # build, check them locally...
docker login
IMAGE=user/sqlalchemy-rest-api deployments/push.sh             # ...then push every variant
IMAGE=user/sqlalchemy-rest-api deployments/push.sh postgres    # or only some
```

The `docker` GitHub Actions workflow does the same by hand (Actions > docker > Run workflow) for a
version already published on PyPI: it builds the tag `v<version>` for amd64 and arm64 and pushes it to Docker Hub.
It needs the repository variable `DOCKERHUB_USERNAME` and the secret `DOCKERHUB_TOKEN`.

The image can serve another app with `APP` (a file of the repository), adding the extras it needs to `EXTRAS`,
e.g. the JWT example (extra `jwt`) instead of `deployments/app.py`. With `build.sh`: `APP=... ADD_EXTRAS=jwt`
adds it to every variant. `PACKAGES` installs pip packages that are not extras (not pinned by `uv.lock`):

```bash
docker build -f deployments/Dockerfile --build-arg APP=example/api_fastapi_jwt.py \
  --build-arg EXTRAS=async,postgres,jwt -t sqlalchemy-rest-api:jwt .
docker run -d -p 8000:8000 -v $PWD/config.json:/app/config/config.json:ro \
  -e JWT_JWKS_URL=https://idp.example.com/realms/x/protocol/openid-connect/certs \
  -e JWT_ISSUER=https://idp.example.com/realms/x -e JWT_AUDIENCE=api -e JWT_ROLE_CLAIM=realm_access.roles \
  sqlalchemy-rest-api:jwt
```

The published images (from 0.3.1, `build.sh` adds `jwt` to every variant) already have PyJWT, so the JWT
example can also run without building: `deployments/compose-jwt.yaml` mounts `example/api_fastapi_jwt.py`
as `/app/app.py` (settings in `deployments/config_jwt.json`, copied from `deployments/config_jwt.example.json`;
users database in the `/app/db` volume). The management commands run in the same container:

```bash
docker compose -f deployments/compose-jwt.yaml run --rm api python app.py init-users-db
docker compose -f deployments/compose-jwt.yaml run --rm api python app.py add-user marta reader
JWT_SECRET="$(openssl rand -hex 32)" JWT_ISSUER=local docker compose -f deployments/compose-jwt.yaml up -d
```

From 0.4.0 the images also have the MCP server (extra `mcp`). `deployments/compose-mcp.yaml` runs it alone or
next to the JWT api, over the same database. It uses its own settings, `deployments/config_mcp.json` (copied from
`deployments/config_mcp.example.json`), because the MCP role is in `"permissions"`, which the JWT settings refuse:

```bash
export MCP_TOKEN="$(openssl rand -hex 32)"   # the MCP client needs the same value

# Only MCP, streamable HTTP on http://127.0.0.1:8001/mcp
docker compose -f deployments/compose-mcp.yaml up -d

# MCP + JWT api on port 8000 (create the users first, see the header of the compose file)
JWT_SECRET="$(openssl rand -hex 32)" JWT_ISSUER=local \
  docker compose -f deployments/compose-mcp.yaml --profile jwt up -d

# stdio in both cases: this is the command of the MCP client
docker compose -f deployments/compose-mcp.yaml run --rm -T mcp-stdio
```

With compose, the `EXTRAS` build argument is read from the environment variable of the same name:

```bash
EXTRAS=postgres,async API_KEYS="admin-secret=admin" docker compose -f deployments/compose.yaml up -d --build
```

Run it with a settings file (`"database"` and `"permissions"`, see `deployments/config.example.json`)
mounted in `/app/config/config.json`:

```bash
docker run -d -p 8000:8000 \
  -v $PWD/config.json:/app/config/config.json:ro \
  -e API_KEYS="admin-secret=admin,reader-secret=reader" \
  sqlalchemy-rest-api
```

| Variable | Default | |
|---|---|---|
| `CONFIG_FILE` | `/app/config/config.json` | settings json; without it the connection comes from `DB_URI` or `DB_TYPE`, `DB_SERVER`... |
| `API_KEYS` | | `key=role` pairs, comma separated, sent in the `X-API-Key` header |
| `API_KEY_HEADER` | `X-API-Key` | header with the api key |
| `DB_ALLOW_RAW_SQL` | `false` | enables `POST /db/sql` |
| `READ_ONLY` | `false` | refuses insert/update/delete/sql |
| `SWAGGER_AUTH` | `false` | "Authorize" button in `/docs` |

With `"permissions"` configured and `API_KEYS` empty every request is refused (401).
Without `"permissions"` every request has full access.

## Examples

See the [example](https://github.com/CarlosRCDev/alchemy-api/tree/main/example) folder: Flask, FastAPI and plain dict usage.
`example/api_fastapi_jwt.py` is a self contained app with JWT authentication (PyJWT) instead of the demo
`X-API-Key` header, without changing the library. It uses the library twice: one `Conexion` for the data
(`"database"`, served by `/db/...`) and another one for a users database (`"users_database"`, default sqlite
`db/db_users.db`, never exposed) with the roles (`api_roles`), the users and their password hashes (`api_users`)
and the operations and tables of each role (`api_role_operations`, `api_role_tables`). Its settings file
(`example/config_jwt.json`) only has the databases: a `"permissions"` section is refused.
Every request needs a valid token; disabling a user, changing its role or its permissions applies at once.
Tokens come from its own login (`JWT_SECRET`, `POST /auth/token`) or from an identity provider
(`JWT_JWKS_URL`, `JWT_PUBLIC_KEY`). The users database is managed with its commands (`init-users-db`,
`add-role`, `delete-role`, `add-user`, `disable-user`, `grant`, `revoke`, `show`); see the docstring of the file.

## License

MIT
