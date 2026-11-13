# AGENTS.md

Library `sqlalchemy-rest-api`, imported as `alchemy_api`: CRUD with plain dicts plus ready-made
Flask/FastAPI routes and an MCP server over **existing** databases via SQLAlchemy reflection (no models).
Backends: sqlite, PostgreSQL (psycopg), MariaDB/MySQL (pymysql/aiomysql), SQL Server (pymssql, sync only),
Oracle (oracledb). Flat layout, Python >= 3.12, build backend `uv_build`.

`CLAUDE.md` is the Claude Code mirror of this file: keep both in sync when rules change.

## Commands

```bash
uv sync                                    # dev env (dev group has every driver/framework)
uv run pytest -q                           # every test, run once per tests/settings/*.json
uv run pytest -q -k config_sqlite          # sqlite only, no containers needed
uv run pytest -q -k "not config_oracle"    # what CI runs (uv run --locked in publish.yml)
uv run pytest tests/test_conexion.py::test_select_all -k config_sqlite

docker compose -f compose-postgres.yaml up -d --wait   # postgres on host port 5433
docker compose -f compose-mariadb.yaml up -d --wait    # mariadb on 3306
docker compose -f compose-mysql.yaml up -d --wait      # mysql on host port 3307
docker compose -f compose-mssql.yaml up -d --wait      # sql server on 1433, creates db "test"
docker compose -f compose-oracle.yaml up -d --wait     # oracle on 1521 (heavy, not in CI)

uv run python example/api_fastapi.py       # demos, run from the repo root
uv run python example/api_flask.py
uv build
```

No formatter, linter or typechecker is configured. Tests are parametrized by the settings files, so
`pytest -q` without a `-k` filter needs all six databases: failures on backends whose container is
down are not code failures.

## Layout

- `alchemy_api/conexion.py` — `Conexion` (sync): reflection, `select` (incl. `join`), `insert`,
  `update`, `delete`, `exec_sql`, `tables`, `schema`, filters, modifiers, rotated file log.
- `alchemy_api/async_conexion.py` — `AsyncConexion(Conexion)`, same API, built with
  `await AsyncConexion.create(...)`; overrides `select/insert/update/delete/exec_sql`.
- `alchemy_api/api_db.py` — Flask blueprints (`api_db`, `api_log`, `api_log_delete`); config in
  `app.config["CNX"|"DB_ROLES"|"DB_TABLES"|"DB_GET_ROLE"|"DB_ALLOW_RAW_SQL"]`.
- `alchemy_api/api_fastapi.py` — FastAPI routers; config in
  `app.state.cnx|roles|tables|get_role|allow_raw_sql`; `_call` awaits async methods and runs sync ones
  in a threadpool.
- `alchemy_api/permissions.py` — `read_permissions` -> `(roles, tables)` maps, `check_permission` /
  `check_table`, `join_tables` (every table in a `join` must be allowed).
- `alchemy_api/mcp_server.py` — `create_mcp(cnx, roles=, tables=, role=, allow_raw_sql=, max_rows=)`
  registers only the role's tools; `http_app` needs `MCP_TOKEN` (>= 32 chars); `main` is the
  `alchemy-api-mcp` command (stdio or http, `show_query` forced off).
- `alchemy_api/utils.py` — `DbException`, `error` namedtuple, `read_cnx_data` (settings json/env ->
  engine args), `env_bool`.
- `tests/settings/*.json` — one file per backend; `tests/conftest.py` re-parametrizes every test with each.
- `deployments/` — Dockerfile, `build.sh` (one image per variant), compose files, `app.py`.
- `example/` — runnable Flask/FastAPI/dict/JWT demos (`config.json`, `demo_data.py`).

## Rules for changes

- **Sync and async stay in step.** Every behavior change in a `Conexion` public method needs the same
  in `AsyncConexion`; put shared logic (filters, column checks, join, modifiers) in `Conexion` helpers.
- **Flask and FastAPI stay in step.** Same endpoints, bodies, status codes and permission names in
  `api_db.py` and `api_fastapi.py`; update the endpoint table in `README.md` too.
- **Errors**: raise `DbException(error(text, status_code))` with `from None`; never leak raw driver
  exceptions. Respect `self._raise` for column validation.
- **Safety guards are intentional, do not weaken**: `update`/`delete` require `filterby` and refuse a
  statement without WHERE (`_require_filterby`, `_require_where`); `read_only` / `READ_ONLY` blocks
  writes with 403; `/db/sql` is off unless enabled; roles configured without `get_role` fail closed
  (500); MCP http refuses to start without `MCP_TOKEN`.
- **Raw SQL** only with bind parameters (`exec_sql(..., bind={...})`), never string formatting.
- **Optional dependencies**: the core install is only `sqlalchemy`. Never import flask, fastapi,
  greenlet, aiosqlite or drivers at module level from `conexion.py`, `utils.py` or `__init__.py`
  (`AsyncConexion` is lazy via `__getattr__`; `oracledb` is imported inside `read_cnx_data`).
  A new extra also goes in the `all` extra in `pyproject.toml` and in `requirements.txt`
  (`uv export --frozen --no-dev --all-extras --no-emit-project -o requirements.txt`).
- **Oracle**: names come back uppercase; `modifiers` (`lower_table`, `lower_cols`, `ret_upper_table`,
  `ret_upper_cols`) handle it. A `limit < 1` means a percentage. Check new features against these.
- **SQL Server**: `OFFSET` needs `ORDER BY` (`_offset` adds the primary key when there is no `orderby`);
  percent limits use `TOP (:p) PERCENT` (`_limit`). No async driver is tested (`NO_ASYNC_DRIVER`).
- **Tests**: add them to the generic files so fixtures run them on every backend (`cnx`,
  `cnx_no_raise`, `db_cfg`, `async_db_cfg`, `roles`, `tables`). Backend-specific tests skip themselves
  via the `backend` fixture (see `tests/test_oracle.py`, `tests/test_mssql.py`). The `users` fixture
  table is dropped and recreated per test.
- **Style**: English for code, comments, docs and commit messages; type hints in the existing
  `name:type` style; small private helpers prefixed with `_`.
- Public API changes (arguments, filter/join shapes, endpoints, settings keys, CLI options) need a
  `README.md` update; keep `CLAUDE.md` in sync when the change affects workflow rules.

## Docker / release

- Images: `deployments/build.sh [variants]` tags `<variant>` and `<version>-<variant>`; `--push` needs
  `IMAGE=user/sqlalchemy-rest-api`; `PLATFORMS` requires `--push`. Variants come from
  `deployments/variants.sh` (unknown variant = error). `deployments/push.sh` only pushes existing local tags.
- `.github/workflows/docker.yml` is manual (`workflow_dispatch`) and builds a tag already on PyPI;
  it needs repo var `DOCKERHUB_USERNAME` and secret `DOCKERHUB_TOKEN`.
- Release: bump `version` in `pyproject.toml`, run `uv lock`, commit/push to main, then `./release.sh`
  (checks clean tree, HEAD = origin/main, free tag/version, tests) which pushes tag `vX.Y.Z`.
  `.github/workflows/publish.yml` then tests (`-k "not config_oracle"`), builds and publishes to
  TestPyPI then PyPI via Trusted Publishing. CI uses `--locked`, so `uv.lock` must match.
- Never run `publish.sh` locally (it uploads directly and breaks the pipeline), and do not push tags or
  publish without being asked.

## Secrets / local files

- Do not read `.env`, `.env.*`, `.publish.env` or `publish.sh` (credentials; denied in `.claude/settings.json`).
- Root `settings/` is git-ignored local config (real credentials). `tests/settings/` is versioned and
  holds only test credentials. `deployments/config*.json` are ignored; only `*.example.json` is versioned.
- Generated at runtime, don't commit: `dist/`, `db/`, `logdb/`, `tests/db/`, `example/db/`, `example/logdb/`.
- `openspec/`, `.opencode/`, `.agents/` are git-ignored local tooling state (OpenSpec workflow, OpenCode config).
