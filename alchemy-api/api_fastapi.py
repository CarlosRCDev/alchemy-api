from inspect import iscoroutinefunction
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, StrictBool

from .utils import DbExecption, error
### FUNCTIONS ###
# Equivalent of api_db.py for FastAPI. The connection (Conexion or AsyncConexion)
# is read from app.state.cnx and raw SQL is enabled with app.state.allow_raw_sql.
#
#   app = FastAPI()
#   app.state.cnx = Conexion(...)  # or await AsyncConexion.create(...)
#   register_exception_handlers(app)
#   app.include_router(api_db, prefix="/db")
#   app.include_router(api_log, prefix="/log")
#   app.include_router(api_log_delete, prefix="/delete_log")
api_db = APIRouter(tags=["db"])
api_log = APIRouter(tags=["log"])
api_log_delete = APIRouter(tags=["delete_log"])

"""--------------------------------------------------------------
|                       Metodos Generales                      |
--------------------------------------------------------------"""
#Metodos generales (select,insert,delete,update) incluidos para testing.

def register_exception_handlers(app: FastAPI):
    @app.exception_handler(DbExecption)
    async def api_db_error(request: Request, err: DbExecption):
        return JSONResponse(
            {"error": str(err), "url": str(request.url)},
            status_code=getattr(err, "status_code", None) or 500,
        )

    @app.exception_handler(Exception)
    async def error_handler(request: Request, err: Exception):
        return JSONResponse({"error": str(err)}, status_code=500)


def get_cnx(request: Request):
    cnx = getattr(request.app.state, "cnx", None)
    if cnx is None:
        raise DbExecption(error("Connection not configured in app.state.cnx", 500)) from None
    return cnx


async def _call(method, *args, **kwargs):
    # AsyncConexion methods are awaited, sync ones run in a thread to not block the event loop
    if iscoroutinefunction(method):
        return await method(*args, **kwargs)
    return await run_in_threadpool(method, *args, **kwargs)


class SelectBody(BaseModel):
    table: str
    colset: list[str] | None = None
    filterby: dict[str, Any] | list[dict[str, Any]] | None = None
    orderby: dict[str, bool] | None = None
    offset: int | None = None
    limit: float | None = None
    count: bool = False
    send_colnames: bool = True
    dt_format: str | None = None


class InsertBody(BaseModel):
    table: str
    data: dict[str, Any] | list[dict[str, Any]]


class DeleteBody(BaseModel):
    table: str
    filterby: dict[str, Any] | list[dict[str, Any]]


class UpdateBody(BaseModel):
    table: str
    data: dict[str, Any]
    filterby: dict[str, Any] | list[dict[str, Any]]


class SchemaBody(BaseModel):
    table: str


class SqlBody(BaseModel):
    statement: str
    parameters: dict[str, Any] = {}
    ret: StrictBool = False


@api_db.post("/select")
async def select(body: SelectBody, cnx=Depends(get_cnx)):
    db_data = body.model_dump(exclude_unset=True)
    table = db_data.pop("table")
    return await _call(cnx.select, table=table, **db_data)


@api_db.post("/insert")
async def insert(body: InsertBody, cnx=Depends(get_cnx)):
    if not body.data: raise DbExecption(error("Not data in post", 400)) from None
    result_db = await _call(cnx.insert, table=body.table, data=body.data)
    return {"insert": sum(map(lambda x: x.is_insert, result_db))}


@api_db.post("/delete")
async def delete(body: DeleteBody, cnx=Depends(get_cnx)):
    if not body.filterby: raise DbExecption(error("Not filterby in post", 400)) from None
    result_db = await _call(cnx.delete, table=body.table, filterby=body.filterby)
    return {"delete": result_db.rowcount}


@api_db.post("/update")
async def update(body: UpdateBody, cnx=Depends(get_cnx)):
    if not body.data: raise DbExecption(error("Not data in post", 400)) from None
    if not body.filterby: raise DbExecption(error("Not filterby in post", 400)) from None
    result_db = await _call(cnx.update, table=body.table, data=body.data, filterby=body.filterby)
    return {"update": result_db.rowcount}


@api_db.get("/tables")
async def tables(cnx=Depends(get_cnx)):
    tables, views = cnx.tables()
    return {"tables": tables, "views": views}


@api_db.post("/schema")
async def schema(body: SchemaBody, cnx=Depends(get_cnx)):
    return cnx.schema(body.table)


@api_db.post("/sql")
async def sql(body: SqlBody, request: Request, cnx=Depends(get_cnx)):
    # Raw SQL is only allowed when the app enables it explicitly
    if not getattr(request.app.state, "allow_raw_sql", False):
        raise DbExecption(error("Endpoint /sql disabled, set app.state.allow_raw_sql", 403)) from None

    result_db = await _call(cnx.exec_sql, statement=body.statement, ret=body.ret, bind=body.parameters)
    if body.ret:
        return result_db
    return Response(status_code=204)


@api_log.get("")
async def log_list(cnx=Depends(get_cnx)):
    return cnx.list_logs()


@api_log.get("/order/{date}")
async def log_date_order(date: str, cnx=Depends(get_cnx)):
    return await _call(cnx.date_logs_order, date)


@api_log.get("/reverse/{date}")
@api_log.get("/reverse/{date}/{n_line}")
async def log_date_reverse(date: str, n_line: int | None = None, cnx=Depends(get_cnx)):
    return await _call(cnx.date_logs_reverse, date, n_line)


@api_log_delete.delete("/{date}")
async def delete_date(date: str, cnx=Depends(get_cnx)):
    cnx.delete_date_logs(date)
    return {"msg": f"Removed log: {date}"}
