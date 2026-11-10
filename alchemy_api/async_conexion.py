
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy import inspect as db_inspect
from sqlalchemy import insert as db_insert
from sqlalchemy import delete as db_delete
from sqlalchemy import update as db_update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.elements import TextClause

from .utils import DbException, error, to_dict
from .conexion import Conexion

class AsyncConexion(Conexion):
    def __init__(self, cnx_data, *, cnx_data_extra:dict=None, show_query:bool=False, modifiers:dict=None, config_log:dict=None, _raise:bool=True, read_only:bool=None, engine=None, sess_maker=None) -> None:
        if not engine:
            engine = create_async_engine(cnx_data, **(cnx_data_extra or {}))
        
        if not sess_maker:
            sess_maker = async_sessionmaker(engine)
        
        super().__init__(cnx_data, cnx_data_extra=cnx_data_extra, show_query=show_query, modifiers=modifiers, config_log=config_log, _raise=_raise, read_only=read_only, engine=engine, sess_maker=sess_maker)

    @classmethod
    async def create(cls, cnx_data, **kwargs):
        instance = cls(cnx_data, **kwargs)
        await instance.async_post_conexion()
        return instance

    async def async_post_conexion(self):
        """Call after __init__ to do async reflection"""
        self._metadata = MetaData()
        async with self._engine.connect() as conn:
            self._views = await conn.run_sync(
                lambda sync_conn: db_inspect(sync_conn).get_view_names()
            )
            await conn.run_sync(
                lambda sync_conn: self._metadata.reflect(sync_conn, views=True)
            )
        return self

    @asynccontextmanager
    async def _async_session(self):
        async with self._sessionmaker() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                str_error = str(e)
                self._logger.error(str_error.replace("\n", "\\n"))
                raise DbException(error(str_error, 400)) from None
            finally:
                await session.close()
    
    async def select(self, table:str, *, colset:list=None, filterby:dict=None, orderby:dict=None, offset:int=None,limit:float=None, count:bool=False, send_colnames:bool=True, dt_format:str=None, join:list=None, **kwargs):
        statement, colnames = self._select_statement(
            table, colset=colset, filterby=filterby, orderby=orderby, offset=offset, limit=limit, count=count, join=join,
        )
        async with self._async_session() as session:
            self._show_query(statement)
            result = await session.execute(statement)
            result = result.all()
        return self._select_result(statement, result, colnames, count=count, send_colnames=send_colnames, dt_format=dt_format)

    async def insert(self, table:str, data:list, **kwargs):
        self._require_writable()
        if isinstance(data, dict):
            data = [data]
        _table = self._get_table(table)
        rows = self._insert_rows(data)
        if not rows:
            return 0

        async with self._async_session() as session:
            for statement, group in self._insert_groups(_table, rows):
                await session.execute(statement, group)
            await session.commit()

        return len(rows)

    async def delete(self, table:str, filterby:dict, **kwargs):
        self._require_writable()
        _table = self._get_table(table)

        statement = db_delete(_table)
        self._require_filterby(filterby)
        if self._lower_cols:
            filterby = self._to_lower_cols(filterby)
        cols_statement = self._cols_in_filter(filterby)
        columns = self._get_columns(statement, cols_statement)

        if self._raise:
            cols_error = list(filter(lambda x: x not in columns, cols_statement))
            if any(cols_error): raise DbException(error(f"filterby: Cols: {', '.join(cols_error)} not find in table", 400)) from None
        statement = self._filterby(_table, statement, columns, filterby)
        self._require_where(statement)

        async with self._async_session() as session:
            self._show_query(statement)
            result = await session.execute(statement)
            await session.commit()

        return result.rowcount
    
    async def update(self, table:str, data:dict, *, filterby:dict=None, **kwargs):
        self._require_writable()
        _table = self._get_table(table)

        statement = db_update(_table)
        self._require_filterby(filterby)
        if self._lower_cols:
            filterby = self._to_lower_cols(filterby)
            data = self._to_lower_cols(data)
        cols_statement = self._cols_in_filter(filterby)
        columns = self._get_columns(statement, cols_statement)

        if self._raise:
            cols_error = list(filter(lambda x: x not in columns, cols_statement))
            if any(cols_error): raise DbException(error(f"Cols: {', '.join(cols_error)} not find in table", 400)) from None

        statement = self._filterby(_table, statement, columns, filterby)
        self._require_where(statement)
        for col_k, col_v in data.items():
            if isinstance(col_v, dict) and "dt_format" in col_v:
                data[col_k] = self._to_datetime(col_v)

        """
        # ✅ No mutation during iteration
        data = {
            col_k: self._to_datetime(col_v) if isinstance(col_v, dict) and "dt_format" in col_v else col_v
            for col_k, col_v in data.items()
        }
        """
        
        statement = statement.values(data)
        async with self._async_session() as session:
            self._show_query(statement)
            result = await session.execute(statement)
            await session.commit()

        return result.rowcount

    async def exec_sql(self, statement, *, ret:bool=False, bind:dict=None):
        self._require_writable()
        if bind is None:
            bind = {}
        if isinstance(statement, str):
            statement = TextClause(statement)
        async with self._async_session() as session:
            self._show_query(statement, bindparams=bind)
            result = await session.execute(statement, params=bind)
            await session.commit()
            if ret:                
                return to_dict(result.all())            
            return result