# CLAUDE.md

Library `sqlalchemy-rest-api` (imported as `alchemy_api`): CRUD with plain dicts plus ready-made
Flask/FastAPI routes over **existing** databases via SQLAlchemy reflection (no models).
Supports sqlite, PostgreSQL (psycopg), MariaDB and MySQL (pymysql/aiomysql), SQL Server (pymssql, sync only) and Oracle (oracledb).

## Commands

Everything goes through `uv` (Python >= 3.12, flat layout, build backend `uv_build`).

```bash
uv sync                                   # dev env (dev group has every driver/framework)
uv run pytest -q                          # all tests, once per tests/settings/*.json
uv run pytest -q -k config_sqlite         # only sqlite (no containers needed)
uv run pytest -q -k "not config_oracle"   # what CI runs
uv run pytest tests/test_conexion.py::test_select_all -k config_sqlite

docker compose -f compose-postgres.yaml up -d --wait   # postgres on host port 5433
docker compose -f compose-mariadb.yaml up -d --wait    # mariadb on 3306
docker compose -f compose-mysql.yaml up -d --wait      # mysql on host port 3307
docker compose -f compose-mssql.yaml up -d --wait      # sql server on 1433 (creates db "test")
docker compose -f compose-oracle.yaml up -d --wait     # oracle on 1521 (heavy, not in CI)

uv run python example/api_fastapi.py      # demo apps, run from the repo root
uv run python example/api_flask.py
uv build
```

When only sqlite is available locally, run with `-k config_sqlite`; failures in other
backends because the container is down are not code failures.

## Layout

- `alchemy_api/conexion.py` — `Conexion` (sync): reflection, `select/insert/update/delete/exec_sql/tables/schema`, filters, modifiers, rotated file log.
- `alchemy_api/async_conexion.py` — `AsyncConexion(Conexion)`: same API, `async` methods, built with `await AsyncConexion.create(...)`.
- `alchemy_api/api_db.py` — Flask blueprints (`api_db`, `api_log`, `api_log_delete`), config in `app.config["CNX"|"DB_ROLES"|"DB_GET_ROLE"|"DB_ALLOW_RAW_SQL"]`.
- `alchemy_api/api_fastapi.py` — FastAPI routers, config in `app.state.cnx|roles|get_role|allow_raw_sql`; `_call` awaits async methods and runs sync ones in a threadpool.
- `alchemy_api/permissions.py` — `read_roles` / `check_permission` (role -> allowed operations).
- `alchemy_api/utils.py` — `DbException`, `error` namedtuple, `read_cnx_data` (settings json/env vars -> engine args), `env_bool`.
- `tests/settings/*.json` — one file per backend; `conftest.py` parametrizes every test with each file.
- `example/` — runnable Flask/FastAPI/dict demos (`config.json`, `demo_data.py`).

## Rules for changes

- **Keep sync and async in step.** Any behavior change in a `Conexion` public method must be
  mirrored in `AsyncConexion` (it overrides `select/insert/update/delete/exec_sql`). Shared logic
  (filters, column checks, modifiers) belongs in `Conexion` helpers so both use it.
- **Keep Flask and FastAPI in step.** Same endpoints, bodies, status codes and permission names
  in `api_db.py` and `api_fastapi.py`. Update the endpoint table in `README.md` too.
- **Errors**: raise `DbException(error(text, status_code))` with `from None`; never leak raw
  driver exceptions from public methods. Respect `self._raise` for column validation.
- **Safety guards are intentional — don't weaken them**: `update`/`delete` require `filterby`
  and refuse a statement with no WHERE (`_require_filterby`, `_require_where`); `read_only`
  (or `READ_ONLY` env) blocks writes with 403; `/db/sql` is off unless explicitly enabled;
  roles configured without `get_role` fail closed (500), never open.
- **Raw SQL** only with bind parameters (`exec_sql(..., bind={...})`), never string formatting.
- **Optional dependencies**: the core install is only `sqlalchemy`. Never import flask, fastapi,
  greenlet, aiosqlite or drivers at module level from `conexion.py`, `utils.py` or `__init__.py`
  (`AsyncConexion` is lazy-loaded via `__getattr__`; `oracledb` is imported inside `read_cnx_data`).
  New extras must also be added to the `all` extra in `pyproject.toml`.
- **Oracle**: table/column names come back uppercase; `modifiers` (`lower_table`, `lower_cols`,
  `ret_upper_table`, `ret_upper_cols`) handle that. `limit < 1` means a percentage. Check new
  features against these modifiers.
- **SQL Server**: `OFFSET` needs `ORDER BY` (`_offset` adds the primary key when there is no
  orderby) and percent limits use `TOP (:p) PERCENT` (`_limit`). No async driver is tested
  (aioodbc needs the system ODBC driver), so async tests skip on mssql (`NO_ASYNC_DRIVER`).
- **Tests**: add tests to the generic files so they run on every backend through the fixtures
  (`cnx`, `cnx_no_raise`, `async_db_cfg`, `db_cfg`, `roles`). Backend-specific tests skip
  themselves (see `tests/test_oracle.py`). The `users` fixture table is recreated per test.
- **Style**: English for code, comments and docs; type hints in the existing `name:type` style;
  small private helpers prefixed with `_`. No formatter/linter is configured — match surrounding code.
- Public API changes (method arguments, filter types, endpoints, settings keys) need a `README.md`
  update.

## Release

1. Bump `version` in `pyproject.toml` and run `uv lock` (CI runs `uv run --locked`, so
   `uv.lock` must match).
2. Commit, then tag `vX.Y.Z` (must equal the pyproject version) and push the tag.
3. `.github/workflows/publish.yml` runs tests (sqlite/postgres/mariadb/mysql/mssql), builds and publishes to
   TestPyPI then PyPI via Trusted Publishing.

Don't push tags or publish without being asked.

## Secrets / local files

- Do not read `.env`, `.env.*`, `.publish.env` or `publish.sh` (they may contain credentials;
  most are denied in `.claude/settings.json`).
- Root `settings/` is git-ignored local config (may hold real credentials); `tests/settings/`
  is versioned and only has test credentials.
- `dist/`, `db/`, `logdb/`, `tests/db/`, `example/db/` are generated at runtime.
