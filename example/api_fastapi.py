"""REST api with FastAPI

Run from the project root (uvicorn comes with the [fastapi] extra):
    uv run python example/api_fastapi.py
Other settings file (default example/config.json):
    CONFIG_FILE=tests/settings/config_oracle.json uv run python example/api_fastapi.py

Docs: http://127.0.0.1:8000/docs
"Authorize" button in the docs to send the X-API-Key header (off by default):
    SWAGGER_AUTH=true uv run python example/api_fastapi.py
Try it (orderby {"col": true} is descending, false ascending):
    curl http://127.0.0.1:8000/db/tables -H "X-API-Key: reader-key"
    curl -X POST http://127.0.0.1:8000/db/select -H "X-API-Key: reader-key" -H "Content-Type: application/json" \
         -d '{"table": "users", "filterby": {"age": 30}, "orderby": {"name": true}}'
    curl http://127.0.0.1:8000/log -H "X-API-Key: admin-key"
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.security import APIKeyHeader

from alchemy_api import Conexion, __version__
from alchemy_api.api_fastapi import api_db, api_log, api_log_delete, register_exception_handlers
from alchemy_api.utils import env_bool
from demo_data import API_KEY_HEADER, create_demo_table, get_role, load_config, load_roles


@asynccontextmanager
async def lifespan(app):
    # The routers read the connection from app.state.cnx.
    # For an async driver use: app.state.cnx = await AsyncConexion.create(**config)
    app.state.cnx = Conexion(**load_config())
    create_demo_table(app.state.cnx)
    # /db/sql is disabled unless this is True
    app.state.allow_raw_sql = False
    # Permissions from the "roles" section of the settings file (None: no control)
    app.state.roles = load_roles()
    app.state.get_role = get_role
    yield
    app.state.cnx._engine.dispose()


def swagger_auth_options():
    """FastAPI options for the "Authorize" button in /docs, only if SWAGGER_AUTH is on"""
    if not env_bool("SWAGGER_AUTH"):
        return {}
    # Declares the header in the OpenAPI schema; the role check is still done by get_role.
    # auto_error=False: a missing key is handled by the library (401 "Role required")
    api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
    return {
        "dependencies": [Depends(api_key_header)],
        # Swagger keeps the key in the browser after reloading the page
        "swagger_ui_parameters": {"persistAuthorization": True},
    }


# Swagger version: installed version of the library
app = FastAPI(
    title="sqlalchemy-rest-api",
    version=__version__,
    lifespan=lifespan,
    **swagger_auth_options(),
)
register_exception_handlers(app)
app.include_router(api_db, prefix="/db")
app.include_router(api_log, prefix="/log")
app.include_router(api_log_delete, prefix="/delete_log")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
