"""REST api with FastAPI

Run from the project root (uvicorn is not a project dependency):
    PYTHONPATH=. uv run --with uvicorn python example/api_fastapi.py

Docs: http://127.0.0.1:8000/docs
Try it (orderby {"col": true} is descending, false ascending):
    curl http://127.0.0.1:8000/db/tables
    curl -X POST http://127.0.0.1:8000/db/select -H "Content-Type: application/json" \
         -d '{"table": "users", "filterby": {"age": 30}, "orderby": {"name": true}}'
    curl http://127.0.0.1:8000/log
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from alchemy_api import Conexion
from alchemy_api.api_fastapi import api_db, api_log, api_log_delete, register_exception_handlers
from demo_data import create_demo_table, load_config


@asynccontextmanager
async def lifespan(app):
    # The routers read the connection from app.state.cnx.
    # For an async driver use: app.state.cnx = await AsyncConexion.create(**config)
    app.state.cnx = Conexion(**load_config())
    create_demo_table(app.state.cnx)
    # /db/sql is disabled unless this is True
    app.state.allow_raw_sql = False
    yield
    app.state.cnx._engine.dispose()


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)
app.include_router(api_db, prefix="/db")
app.include_router(api_log, prefix="/log")
app.include_router(api_log_delete, prefix="/delete_log")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
