# sqlalchemy-rest-api

CRUD with python dicts and an automatic REST api (Flask or FastAPI) over **existing databases**.
Tables are read with SQLAlchemy reflection: no models to write.

- `select`, `insert`, `update`, `delete`, `exec_sql` with plain dicts and lists
- Filters with operators (`>`, `in`, `between`, `like`, `startswith`, ...) and `or` groups
- Sync (`Conexion`) and async (`AsyncConexion`) classes
- Ready-made routes for Flask (blueprints) and FastAPI (routers)
- Daily rotated file log, readable through the api
- Oracle friendly: modifiers for upper/lower case tables and columns

## Install

```bash
pip install sqlalchemy-rest-api            # core
pip install "sqlalchemy-rest-api[flask]"   # + Flask api
pip install "sqlalchemy-rest-api[fastapi]" # + FastAPI api
pip install "sqlalchemy-rest-api[async]"   # + AsyncConexion
```

Database drivers: `[oracle]`, `[mariadb]`, `[postgres]` (sqlite needs nothing; async sqlite needs `aiosqlite`).

The package is imported as `alchemy_api`.

## Usage with a dict

```python
from alchemy_api import Conexion
from alchemy_api.utils import read_cnx_data

config = {
    "type": "sqlite",  # oracle, mariadb, async_mariadb, psycopg, sqlite
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
cnx.update("users", {"age": 41}, filterby={"id": 10}).rowcount
cnx.delete("users", filterby={"id": 10}).rowcount
cnx.exec_sql("SELECT name FROM users WHERE age = :age", ret=True, bind={"age": 25})
```

A plain SQLAlchemy url also works: `Conexion("sqlite:///example.db")`.

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

| Method | Path | Body |
|---|---|---|
| GET | `/db/tables` | |
| POST | `/db/schema` | `{"table": "users"}` |
| POST | `/db/select` | `{"table": "users", "filterby": {...}, "orderby": {...}, "colset": [...]}` |
| POST | `/db/insert` | `{"table": "users", "data": [{...}]}` |
| POST | `/db/update` | `{"table": "users", "data": {...}, "filterby": {...}}` |
| POST | `/db/delete` | `{"table": "users", "filterby": {...}}` |
| POST | `/db/sql` | `{"statement": "...", "parameters": {...}, "ret": true}` (only if enabled) |
| GET | `/log` | list of log dates |
| GET | `/log/order/{date}` | log lines |
| GET | `/log/reverse/{date}/{n_line}` | last lines first |
| DELETE | `/delete_log/{date}` | removes an old log |

## Examples

See the [example](https://github.com/CarlosRCDev/alchemy-api/tree/main/example) folder: Flask, FastAPI and plain dict usage.

## License

MIT
