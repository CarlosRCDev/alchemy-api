
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy import inspect as db_inspect
from sqlalchemy import select as db_select
from sqlalchemy import insert as db_insert
from sqlalchemy import delete as db_delete
from sqlalchemy import update as db_update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.elements import TextClause

from .utils import DbExecption, error, to_dict
from .conexion import Conexion

class AsyncConexion(Conexion):
    def __init__(self, cnx_data, *, cnx_data_extra:dict={}, show_query:bool=False, modifiers:dict={}, config_log:dict={}, _raise:bool=True, engine=None, sess_maker=None) -> None:
        if not engine:
            self.__engine = create_async_engine(cnx_data, **cnx_data_extra)
        
        if not sess_maker:
            self.__sessionmaker = async_sessionmaker(self.__engine)
        
        super().__init__(cnx_data, cnx_data_extra=cnx_data_extra, show_query=show_query, modifiers=modifiers, config_log=config_log, _raise=_raise, engine=self.__engine, sess_maker=self.__sessionmaker)

    @classmethod
    async def create(cls, cnx_data, **kwargs):
        instance = cls(cnx_data, **kwargs)
        await instance.async_post_conexion()
        return instance

    async def async_post_conexion(self):
        """Call after __init__ to do async reflection"""
        self._metadata = MetaData()
        async with self.__engine.connect() as conn:
            self._views = await conn.run_sync(
                lambda sync_conn: db_inspect(sync_conn).get_view_names()
            )
            await conn.run_sync(
                lambda sync_conn: self._metadata.reflect(sync_conn, views=True)
            )
        return self

    @asynccontextmanager
    async def __Session(self):
        async with self.__sessionmaker() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                str_error = str(e)
                self.__logger.error(str_error.replace("\n", "\\n"))
                raise DbExecption(error(str_error, 400)) from None
            finally:
                await session.close()
    
    async def select(self, table:str, *, colset:list=None, filterby:dict=None, orderby:dict=None, offset:int=None,limit:float=None, count:bool=False, send_colnames:bool=True, dt_format:str=None, **kwargs):
        _table = self._get_table(table)
        if count:
            statement = db_select(func.count('*')).select_from(_table)
        elif colset:
            if self._lower_cols:
                colset = self._to_lower_cols(colset)
            statement = db_select(*self._colset(_table, colset))
        else:
            statement = db_select(_table)

        columns_table = self._get_columns(_table)

        if self._lower_cols and colset:
            colset = self._to_lower_cols(colset)

        if self._raise and colset:
            cols_error = list(filter(lambda x: x not in columns_table, colset))
            if any(cols_error): raise DbExecption(error(f"Cols: {', '.join(cols_error)} not find in table", 400)) from None

        if filterby:
            if self._lower_cols:
                filterby = self._to_lower_cols(filterby)
            if self._raise:
                if isinstance(filterby, list):
                    cols = [item for sublist in [[x.get("key")] if x.get("key") else list(x.keys()) for x in filterby] for item in sublist]
                    cols_error = list(filter(lambda x: x not in columns_table, cols))
                else:
                    cols_error = list(filter(lambda x: x not in columns_table, filterby.keys()))
                if any(cols_error): raise DbExecption(error(f"filterby: Cols: {', '.join(cols_error)} not find in table", 400)) from None
                
            statement = self._filterby(_table, statement, columns_table, filterby)
        
        if orderby and not count:
            if self._lower_cols:
                orderby = self._to_lower_cols(orderby)
            statement = self._orderby(statement, _table, orderby)
        
        if offset and not count:
            statement = self._offset(statement, offset)
        
        if limit and not count:
            statement = self._limit(statement, limit)

        async with self.__Session() as session:
            self._show_query(statement)
            result = await session.execute(statement)
            result = result.all()
        if dt_format:
            result = [[col.strftime(dt_format) if isinstance(col, datetime) else col for col in row] for row in result]
        
        if send_colnames:
            columns_colset = self._get_columns(statement)
            if self._ret_upper_cols:
                columns_colset = self._to_upper_cols(columns_colset)
            result = self._colnames(columns_colset, result)
            return result[0] if count else result
        else:
            result = list(map(list,result))
            return result[0] if count else result

    async def insert(self, table:str, data:list, **kwargs):
        if isinstance(data, dict):
            data = [data]
        _table = self._get_table(table)

        statement = db_insert(_table)

        if self._lower_cols:
            data = self._to_lower_cols(data)
        
        result = []
        async with self.__Session() as session:
            for row in data:
                # for col_k, col_v in row.items():
                    # if isinstance(col_v, dict) and "dt_format" in col_v:
                        # row[col_k] = self._to_datetime(col_v)
                row = {
                    col_k: self._to_datetime(col_v) if isinstance(col_v, dict) and "dt_format" in col_v else col_v
                    for col_k, col_v in row.items()
                }
                _statement = statement.values(row)
                self._show_query(statement, bindparams=row)
                row_result = await session.execute(_statement)
                result.append(row_result)
            await session.commit()

        return result

    async def delete(self, table:str, filterby:dict, **kwargs):
        ### TODO ###
        # add lower case and upper case methods like others
        _table = self._get_table(table)

        statement = db_delete(_table)
        if self._lower_cols:
            filterby = self._to_lower_cols(filterby)
        cols_statement = self._cols_in_filter(filterby)
        columns = self._get_columns(statement, cols_statement)

        if self._raise:
            cols_error = list(filter(lambda x: x not in columns, cols_statement))
            if any(cols_error): raise DbExecption(error(f"filterby: Cols: {', '.join(cols_error)} not find in table", 400)) from None
        statement = self._filterby(_table, statement, columns, filterby)

        async with self.__Session() as session:
            self._show_query(statement)
            result = await session.execute(statement)
            await session.commit()

        return result
    
    async def update(self, table:str, data:dict, *, filterby:dict=None, **kwargs):
        _table = self._get_table(table)

        statement = db_update(_table)
        if self._lower_cols:
            filterby = self._to_lower_cols(filterby)
            data = self._to_lower_cols(data)
        cols_statement = self._cols_in_filter(filterby)
        columns = self._get_columns(statement, cols_statement)

        if self._raise:
            cols_error = list(filter(lambda x: x not in columns, cols_statement))
            if any(cols_error): raise DbExecption(error(f"Cols: {', '.join(cols_error)} not find in table", 400)) from None

        statement = self._filterby(_table, statement, columns, filterby)
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
        async with self.__Session() as session:
            self._show_query(statement)
            result = await session.execute(statement)
            await session.commit()
        
        return result

    async def exec_sql(self, statement, *, ret:bool=False, bind:dict=None):
        if bind is None:
            bind = {}
        if isinstance(statement, str):
            statement = TextClause(statement)
        async with self.__Session() as session:
            ## TODO
            self._show_query(statement, bindparams=bind)
            ## TODO
            result = await session.execute(statement, params=bind)
            await session.commit()
            if ret:                
                return to_dict(result.all())            
            return result