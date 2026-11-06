# sqlalchemy-rest-api

REST API over an **existing** SQL database, with no models or code: tables are discovered with
SQLAlchemy reflection. Select, insert, update and delete with JSON, with permissions per role
(operations and tables) and API keys.

Built from the Python library [sqlalchemy-rest-api](https://pypi.org/project/sqlalchemy-rest-api/)
([source](https://github.com/CarlosRCDev/alchemy-api)), served with FastAPI + uvicorn.

## Tags

One image per database driver, all of them with async support:

| Tag | Databases |
|---|---|
| `latest`, `<version>`, `sqlite`, `<version>-sqlite` | SQLite only (smallest image) |
| `all`, `<version>-all` | every driver below |
| `postgres`, `<version>-postgres` | PostgreSQL |
| `mysql`, `<version>-mysql` | MySQL and MariaDB |
| `mssql`, `<version>-mssql` | SQL Server |
| `oracle`, `<version>-oracle` | Oracle (thin mode, no Oracle client needed) |

Pin `<version>-<driver>` (e.g. `0.3.0-postgres`) in production.

## Quick start

`config.json`:

```json
{
    "database": {
        "type": "psycopg",
        "server": "db.example.com",
        "port": 5432,
        "db": "shop",
        "user": "api",
        "password": "secret"
    },
    "permissions": {
        "admin": {"roles": ["*"], "tables": ["*"]},
        "reader": {"roles": ["tables", "schema", "select"], "tables": ["customers", "orders"]}
    }
}
```

```bash
docker run -d -p 8000:8000 \
  -v "$PWD/config.json:/app/config/config.json:ro" \
  -e API_KEYS="admin-secret=admin,reader-secret=reader" \
  USER/sqlalchemy-rest-api:postgres

curl http://localhost:8000/db/tables -H "X-API-Key: reader-secret"
curl -X POST http://localhost:8000/db/select -H "X-API-Key: reader-secret" -H "Content-Type: application/json" \
     -d '{"table": "orders", "filterby": {"status": "open"}, "orderby": {"created": true}, "limit": 10}'
```

Interactive docs: `http://localhost:8000/docs` (set `SWAGGER_AUTH=true` for the API key button).

`database.type`: `psycopg` (PostgreSQL), `mysql`, `mariadb`, `mssql`, `oracle`, `sqlite`, or a SQLAlchemy URL in `"uri"`.

## Endpoints

| Method | Path | Body | Operation |
|---|---|---|---|
| GET | `/db/tables` | | `tables` |
| POST | `/db/schema` | `{"table": "t"}` | `schema` |
| POST | `/db/select` | `{"table": "t", "filterby": {...}, "orderby": {...}, "colset": [...], "limit": 10, "offset": 0}` | `select` |
| POST | `/db/insert` | `{"table": "t", "data": [{...}]}` | `insert` |
| POST | `/db/update` | `{"table": "t", "data": {...}, "filterby": {...}}` | `update` |
| POST | `/db/delete` | `{"table": "t", "filterby": {...}}` | `delete` |
| POST | `/db/sql` | `{"statement": "...", "parameters": {...}, "ret": true}` (disabled by default) | `sql` |
| GET | `/log`, `/log/order/{date}`, `/log/reverse/{date}` | | `log_read` |
| DELETE | `/delete_log/{date}` | | `log_delete` |
| GET | `/health` | | always open |

`update` and `delete` always need `filterby`: a request can not change or remove a whole table.

## Permissions

Each role in `"permissions"` has the operations (`"roles"`) and the tables (`"tables"`) it can use, `"*"` for all.
The role of a request comes from its API key (`API_KEYS`, header `X-API-Key`).

- No key: 401. Operation or table not allowed: 403.
- `/db/tables` only lists the tables of the role.
- `/db/sql` only for roles with `"tables": ["*"]`.
- With `"permissions"` and no `API_KEYS`, every request is refused. **Without `"permissions"` the API is fully open**: use it only on a private network.

## Configuration

| Variable | Default | |
|---|---|---|
| `CONFIG_FILE` | `/app/config/config.json` | settings file; without it the connection is read from `DB_URI` or `DB_TYPE`, `DB_SERVER`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_DB` |
| `API_KEYS` | | `key=role` pairs, comma separated |
| `API_KEY_HEADER` | `X-API-Key` | header with the API key |
| `DB_ALLOW_RAW_SQL` | `false` | enables `POST /db/sql` |
| `READ_ONLY` | `false` | refuses insert, update, delete and SQL |
| `SWAGGER_AUTH` | `false` | API key button in `/docs` |

| Path | |
|---|---|
| `/app/config/config.json` | settings file (mount read only) |
| `/app/db` | SQLite databases (volume) |
| `/app/logdb` | query log, if `"log"` is set in `"database"` (volume) |

The container runs as a non root user (uid 10001), listens on port 8000 and has a healthcheck on `/health`.
For production also give the database user only the grants it needs (e.g. only `SELECT` for a read only API)
and put the API behind HTTPS.

License: MIT
