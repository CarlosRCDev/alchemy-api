"""REST api server for the Docker image (FastAPI + uvicorn)

Configuration (environment variables):
    CONFIG_FILE       settings json with "database" and optional "permissions" sections
                      (default /app/config/config.json). Without the file, or without "database",
                      the connection is read from DB_URI or DB_TYPE/DB_SERVER/DB_PORT/DB_USER/...
    API_KEYS          api key -> role, "key1=admin,key2=reader". Only used with "permissions"
    API_KEY_HEADER    header with the api key (default X-API-Key)
    DB_ALLOW_RAW_SQL  enables POST /db/sql (default false)
    READ_ONLY         refuses insert/update/delete/sql (default false)
    SWAGGER_AUTH      "Authorize" button in /docs for the api key header (default false)
"""
from contextlib import asynccontextmanager
from hmac import compare_digest
import json
import logging
from os import getenv
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.security import APIKeyHeader

from alchemy_api import Conexion, __version__
from alchemy_api.api_fastapi import api_db, api_log, api_log_delete, register_exception_handlers
from alchemy_api.permissions import read_permissions
from alchemy_api.utils import env_bool, read_cnx_data

logger = logging.getLogger("uvicorn.error")

CONFIG_FILE = Path(getenv("CONFIG_FILE", "/app/config/config.json"))
API_KEY_HEADER = getenv("API_KEY_HEADER", "X-API-Key")


def load_settings() -> dict:
    if not CONFIG_FILE.is_file():
        logger.info("No settings file %s, connection from environment variables", CONFIG_FILE)
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_api_keys() -> dict[str, str]:
    """API_KEYS "key1=role1,key2=role2" -> {key: role}"""
    api_keys = {}
    for item in filter(None, (part.strip() for part in getenv("API_KEYS", "").split(","))):
        key, sep, role = item.partition("=")
        if not sep or not key.strip() or not role.strip():
            raise ValueError("Not valid API_KEYS, format: key1=role1,key2=role2")
        api_keys[key.strip()] = role.strip()
    return api_keys


def make_get_role(api_keys:dict[str, str]):
    def get_role(request):
        sent = request.headers.get(API_KEY_HEADER)
        if not sent:
            return None
        # Constant time comparison, the key is not looked up directly
        for key, role in api_keys.items():
            if compare_digest(sent.encode(), key.encode()):
                return role
        return None
    return get_role


@asynccontextmanager
async def lifespan(app):
    settings = load_settings()
    cnx_data, cnx_data_extra, show_query, modifiers, config_log = read_cnx_data(dict(settings.get("database", {})))
    app.state.cnx = Conexion(
        cnx_data,
        cnx_data_extra=cnx_data_extra,
        show_query=show_query,
        modifiers=modifiers,
        config_log=config_log,
    )
    app.state.allow_raw_sql = env_bool("DB_ALLOW_RAW_SQL")
    app.state.roles, app.state.tables = read_permissions(settings.get("permissions"))
    if app.state.roles is None and app.state.tables is None:
        logger.warning("No \"permissions\" in the settings: every request has full access")
    else:
        api_keys = load_api_keys()
        if not api_keys:
            # get_role always returns None: every request gets 401, never open
            logger.warning("Permissions configured but API_KEYS is empty: every request will be refused")
        app.state.get_role = make_get_role(api_keys)
    yield
    app.state.cnx._engine.dispose()


def swagger_auth_options() -> dict:
    """FastAPI options for the "Authorize" button in /docs, only if SWAGGER_AUTH is on"""
    if not env_bool("SWAGGER_AUTH"):
        return {}
    api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
    return {
        "dependencies": [Depends(api_key_header)],
        "swagger_ui_parameters": {"persistAuthorization": True},
    }


app = FastAPI(title="sqlalchemy-rest-api", version=__version__, lifespan=lifespan, **swagger_auth_options())
register_exception_handlers(app)
app.include_router(api_db, prefix="/db")
app.include_router(api_log, prefix="/log")
app.include_router(api_log_delete, prefix="/delete_log")


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "version": __version__}
