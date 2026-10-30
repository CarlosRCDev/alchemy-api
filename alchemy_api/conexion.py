
from re import sub as re_sub
from contextlib import contextmanager
from datetime import date as date_cls, datetime
import logging
import logging.handlers
from pathlib import Path

from sqlalchemy import create_engine, MetaData, Table, Column, desc, func
from sqlalchemy import inspect as db_inspect
from sqlalchemy import select as db_select
from sqlalchemy import insert as db_insert
from sqlalchemy import delete as db_delete
from sqlalchemy import update as db_update
from sqlalchemy import or_ as db_or, and_ as db_and
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.elements import TextClause

from .utils import DbExecption, error, to_dict, read_file_reverse


def _rotated_log_path(log_path:Path, log_date:str) -> Path:
    """Rotated log keeps the extension of the current log: log.log -> log.<date>.log, log -> log.<date>.log"""
    return log_path.with_name(f"{log_path.stem}.{log_date}{log_path.suffix or '.log'}")


def _log_namer(default_name:str) -> str:
    # default_name is "<log_path>.<date>", as built by TimedRotatingFileHandler
    log_path, _, log_date = default_name.rpartition(".")
    return str(_rotated_log_path(Path(log_path), log_date))


def _configure_logger(config_log):
    log_path = Path(config_log["log_path"]).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"{__name__}.{log_path.resolve()}")
    logger.setLevel(config_log.get("level_log", "INFO"))
    logger.propagate = False

    handler = next(
        (
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.handlers.TimedRotatingFileHandler)
            and Path(handler.baseFilename) == log_path.resolve()
        ),
        None,
    )
    if handler is None:
        # Default suffix/extMatch for "midnight" are "%Y-%m-%d"; the namer also uses
        # them to find old logs to remove with backupCount
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_path,
            when="midnight",
            backupCount=int(config_log.get("backup_count", 10)),
            encoding="utf-8",
        )
        handler.namer = _log_namer
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    else:
        handler.backupCount = int(config_log.get("backup_count", 10))

    logger.info(
        "-----Start Application: LEVEL:%s-----",
        config_log.get("level_log", "INFO"),
    )
    return logger, log_path


class Conexion:
    def __init__(self, cnx_data, *, cnx_data_extra:dict=None, show_query:bool=False, modifiers:dict=None, config_log:dict=None, _raise:bool=True, engine=None, sess_maker=None) -> None:
        modifiers = modifiers or {}
        self.show_query = show_query
        self._raise = _raise
        if engine:
            self._engine = engine
        else:
            self._engine = create_engine(cnx_data, **(cnx_data_extra or {}))

        if sess_maker:
            self._sessionmaker = sess_maker
        else:    
            self._sessionmaker = sessionmaker(self._engine)
        
        self._log_path = None
        self._logger = logging.getLogger(__name__)
        if config_log:
            self._logger, self._log_path = _configure_logger(config_log)

        self._lower_table = modifiers.get("lower_table", False) # Transform table input to lowercase, oracle default
        self._lower_cols = modifiers.get("lower_cols", False) # Transform columns input to lowercase, oracle default 
        self._ret_upper_table = modifiers.get("ret_upper_table", False) # Transform return table in capital case
        self._ret_upper_cols = modifiers.get("ret_upper_cols", False) # Transform return columns in capital case
        
        if isinstance(self._sessionmaker, sessionmaker):
            self.post_conexion()
        
    def post_conexion(self):
        self._metadata = MetaData()
        self._views = db_inspect(self._engine).get_view_names()
        self._metadata.reflect(self._engine, views=True)
    
    @property
    def metadata(self):
        return self._metadata

    # @property
    # def engine(self):
    #     return self._engine

    @property
    def logger(self):
        return self._logger
    
    @contextmanager
    def _session(self):
        with self._sessionmaker() as session:
            try:
                yield session
            except Exception as e:
                str_error = str(e)
                self._logger.error(str_error.replace("\n", "\\n"))
                raise DbExecption(error(str_error, 400)) from None
            finally:
                session.close()

    @classmethod
    def _to_lower_cols(cls, cols):
        if isinstance(cols, dict):
            return {k.lower(): v for k,v in cols.items()}
        elif isinstance(cols, list):
            return [cls._to_lower_cols(col) for col in cols]
        elif isinstance(cols, str):
            return cols.lower()
        else:
            return cols

    @classmethod
    def _to_upper_cols(cls, cols):
        if isinstance(cols, dict):
            return {k.upper(): v for k,v in cols.items()}
        elif isinstance(cols, list):
            return [cls._to_upper_cols(col) for col in cols]
        elif isinstance(cols, str):
            return cols.upper()
        else:
            return cols

    def _valid_columns(self, _table, columns):
        __table = []
        for column in columns:
            _column = _table.c.get(column, None)
            if isinstance(_column, Column):
                __table.append(_column)
            elif self._raise:
                raise DbExecption(error(f"column: {column}, not find in table", 400)) from None
        if __table:
            return __table
        else:
            return None
    
    def _populate(self, tables_):
        """
        Populate by list of names
        """
        with self._session():
            for table in tables_:
                Table(table, self._metadata, autoload_with=self._engine)
    
    def select(self, table:str, *, colset:list=None, filterby:dict=None, orderby:dict=None, offset:int=None,limit:float=None, count:bool=False, send_colnames:bool=True, dt_format:str=None, **kwargs):
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

        with self._session() as session:
            self._show_query(statement)
            result = session.execute(statement).all()
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

    def insert(self, table:str, data:list, **kwargs):
        if isinstance(data, dict):
            data = [data]
        _table = self._get_table(table)

        statement = db_insert(_table)

        if self._lower_cols:
            data = self._to_lower_cols(data)
        
        result = []
        with self._session() as session:
            for row in data:
                for col_k, col_v in row.items():
                    if isinstance(col_v, dict) and "dt_format" in col_v:
                        row[col_k] = self._to_datetime(col_v)
                _statement = statement.values(row)
                self._show_query(_statement, bindparams=row)
                row_result = session.execute(_statement)
                result.append(row_result)
            session.commit()

        return result

    def delete(self, table:str, filterby:dict, **kwargs):
        ### TODO ###
        # add lower case and upper case methods like others
        _table = self._get_table(table)

        statement = db_delete(_table)
        self._require_filterby(filterby)
        if self._lower_cols:
            filterby = self._to_lower_cols(filterby)
        cols_statement = self._cols_in_filter(filterby)
        columns = self._get_columns(statement, cols_statement)

        if self._raise:
            cols_error = list(filter(lambda x: x not in columns, cols_statement))
            if any(cols_error): raise DbExecption(error(f"filterby: Cols: {', '.join(cols_error)} not find in table", 400)) from None
        statement = self._filterby(_table, statement, columns, filterby)
        self._require_where(statement)

        with self._session() as session:
            self._show_query(statement)
            result = session.execute(statement)
            session.commit()

        return result
    
    def update(self, table:str, data:dict, *, filterby:dict=None, **kwargs):
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
            if any(cols_error): raise DbExecption(error(f"Cols: {', '.join(cols_error)} not find in table", 400)) from None

        statement = self._filterby(_table, statement, columns, filterby)
        self._require_where(statement)
        for col_k, col_v in data.items():
            if isinstance(col_v, dict) and "dt_format" in col_v:
                data[col_k] = self._to_datetime(col_v)
        
        statement = statement.values(data)
        with self._session() as session:
            self._show_query(statement)
            result = session.execute(statement)
            session.commit()
         
        return result
    
    def tables(self):
        ret_tables = list(set(self.metadata.tables.keys()) - set(self._views)), self._views
        return [[t.upper() for t in t_v] for t_v in ret_tables] if self._ret_upper_table else ret_tables

    def schema(self, table:str, **kwargs):
        table_ = self._get_table(table)
        schema_ = {}
        schema_["columns"] = {tab.name: repr(tab) for tab in table_.columns}
        schema_["indexes"] = repr(table_.indexes)
        # schema_["foreign_keys"] = repr(table_.foreign_keys)
        # schema_["foreign_key_constraints"] = repr(table_.foreign_key_constraints)
        return schema_

    def exec_sql(self, statement, *, ret:bool=False, bind:dict=None):
        bind = bind or {}
        if isinstance(statement, str):
            statement = TextClause(statement)
        with self._session() as session:
            ## TODO
            self._show_query(statement, bindparams=bind)
            ## TODO
            if ret:
                return to_dict(session.execute(statement, params=bind).all())
            session.execute(statement, params=bind)
            session.commit()

    def _get_table(self, table):
        if self._lower_table:
            table = table.lower()
        _table = self._metadata.tables.get(table, None)
        
        if not isinstance(_table, Table):
            raise DbExecption(error(f"Not find table: {table} in db", 400)) from None
        
        return _table

    def _get_columns(self, statement=None, cols=None):
        # if self._lower_cols:
        #     cols = [col.lower() for col in cols]
        if isinstance(statement, Table): # En realidad es una tabla
            return [x.key for x in statement.c]
        
        cols_statement = []
        if hasattr(statement, "column_descriptions"):
            cols_statement = [x.get("name") for x in statement.column_descriptions]
        elif hasattr(statement, "table"):
            cols_statement = [x for x in statement.table.columns.keys() if x in cols]
        return cols_statement
    
    def _cols_in_filter(self, filterby):
        if isinstance(filterby, list):
            cols = [item for sublist in [[x.get("key")] if x.get("key") else list(x.keys()) for x in filterby] for item in sublist]
        else:
            cols = list(filterby.keys())
        
        return cols
    
    def _require_filterby(self, filterby):
        if not filterby:
            raise DbExecption(error("filterby is required", 400)) from None

    def _require_where(self, statement):
        # Avoid DELETE/UPDATE over the whole table when every filter column was discarded
        if statement.whereclause is None:
            raise DbExecption(error("filterby: no valid conditions, refusing to affect the whole table", 400)) from None

    def _orderby(self, statement, _table, orderby):
        valid_columns = self._valid_columns(_table, orderby.keys())
        if valid_columns:
            statement = statement.order_by(
                *[desc(column) if orderby.get(column.name, False) else column for column in valid_columns]
            )
        return statement

    def _colset(self, _table, colset):
        valid_columns = self._valid_columns(_table, colset)
        
        if valid_columns:
            return valid_columns
        else:
            if self._raise:
                raise DbExecption(error(f"none of the columns are valid, columns: {', '.join(colset)}", 400)) from None
            return [_table]
    
    def _filterby(self, table, statement, columns, filterby):
        if isinstance(filterby, list):
            for filter_column in filterby:
                if filter_column.get("key") and filter_column.get("conditions"):
                    statement = self._filter_by_list(table, statement, columns, filter_column)
                else:
                    statement = self._filter_by_dict(table, statement, columns, filter_column)
        else:
            statement = self._filter_by_dict(table, statement, columns, filterby)
        return statement
    
    def _filter_by_list(self, table, statement, columns, filterby):

        column = filterby.get("key", None)
        conditions = filterby.get("conditions")
        cond_and = filterby.get("and", True)
        statement = self._filter_by_dict(table, statement, columns, {column:conditions}, cond_and=cond_and)
            
        return statement
    
    def _filter_by_dict(self, table, statement, columns, filterby, cond_and=True):
        cond = db_and if cond_and else db_or
        for column, value in dict(filter(lambda x: x[0] in columns, filterby.items())).items():
            col = table.c.get(column)
            values = value if isinstance(value, list) else [value]
            conditions = [c for c in (self._filter_conditions(col, v) for v in values) if c is not None]
            if conditions:
                statement = statement.where(cond(*conditions))
        
        return statement

    def _filter_conditions(self, col, value):
        if isinstance(value, dict):
            type_ = value.get("type", "==")
            if type_ == "==" or type_ == "=":
                condition = col == value.get("value")
            elif type_ == "<=":
                condition = col <= value.get("value")
            elif type_ == "<":
                condition = col < value.get("value")
            elif type_ == ">":
                condition = col > value.get("value")
            elif type_ == ">=":
                condition = col >= value.get("value")
            elif type_ == "!=":
                condition = col != value.get("value")
            elif type_ == "in":
                condition = col.in_(value.get("value"))
            elif type_ == "not_in":
                condition = col.not_in(value.get("value"))
            elif type_ == "is":
                condition = col.is_(value.get("value"))
            elif type_ == "is_not":
                condition = col.is_not(value.get("value"))
            elif type_ == "like":
                condition = col.like(value.get("value"))
            elif type_ == "ilike":
                condition = col.ilike(value.get("value"))
            elif type_ == "not_like":
                condition = col.not_like(value.get("value"))
            elif type_ == "not_ilike":
                condition = col.not_ilike(value.get("value"))
            elif type_ == "contains":
                condition = col.contains(value.get("value"))
            elif type_ == "icontains":
                condition = col.icontains(value.get("value"))
            elif type_ == "startswith":
                condition = col.startswith(value.get("value"))
            elif type_ == "endswith":
                condition = col.endswith(value.get("value"))
            elif type_ == "match":
                condition = col.match(value.get("value"))
            elif type_ == "regexp_match":
                condition = col.regexp_match(value.get("value"))
            elif type_ == "between":
                condition = col.between(value.get("value1"), value.get("value2"))
            elif self._raise:
                raise DbExecption(error(f"none of the type are valid, col: {col}, value: {type_}", 400)) from None
            else:
                condition = None
        else:
            condition = col==value
            
        return condition

    def _colnames(self, columns, result):
        return [dict(zip(columns, row)) for row in result]
    
    def _offset(self, statement, offset):
        return statement.offset(offset)
    
    def _limit(self, statement, limit):
        # limit < 1 is a percentage, only for dialects with FETCH ... PERCENT (Oracle)
        if limit < 1:
            return statement.fetch(limit, percent=True)
        return statement.limit(int(limit))
    
    def _compile(self, statement, bindparams:dict=None):
        if bindparams:
            if not isinstance(statement, TextClause):
                statement = TextClause(str(statement))
            query = statement.bindparams(**bindparams).compile(compile_kwargs={"literal_binds": True})
        else:
            query = statement.compile(bind=self._engine, compile_kwargs={"literal_binds": True})
        return query
    
    def _show_query(self, statement, bindparams:dict=None):
        if self.show_query or self._logger.isEnabledFor(logging.DEBUG):
            try:
                query = self._compile(statement, bindparams=bindparams)
            except Exception as e:
                query = f"Error compiling query: {str(e)}"
            log_query = str(query).replace("\n", "\\n")
            if self.show_query:
                self._logger.info(log_query)
            else:
                self._logger.debug(log_query)
    
    def _to_datetime(self, col_v):
        return datetime.strptime(col_v["value"], col_v["dt_format"])
    
    def list_logs(self):
        if not self._log_path:
            raise DbExecption(error("log not instanciated", 404, False)) from None
        dates = set()
        for log_file in self._log_path.parent.iterdir():
            if not log_file.is_file() or log_file.name == self._log_path.name:
                continue
            log_date = log_file.name[len(self._log_path.stem) + 1:][:10]
            try:
                if _rotated_log_path(self._log_path, date_cls.fromisoformat(log_date).isoformat()) == log_file:
                    dates.add(log_date)
            except ValueError:
                continue
        if self._log_path.is_file():
            dates.add(date_cls.today().isoformat())
        return sorted(dates)

    def _date_log_path(self, log_date:str):
        if not self._log_path:
            raise DbExecption(error("log not instanciated", 404, False)) from None
        try:
            if date_cls.fromisoformat(log_date).isoformat() != log_date:
                return None
        except ValueError:
            return None

        if log_date == date_cls.today().isoformat() and self._log_path.is_file():
            return self._log_path
        rotated_log = _rotated_log_path(self._log_path, log_date)
        return rotated_log if rotated_log.is_file() else None

    def date_logs_order(self, date:str):
        log_path = self._date_log_path(date)
        if log_path:
            with log_path.open("r", encoding="utf-8") as file:
                return file.readlines()
        raise DbExecption(error("date not find", 404, False)) from None

    def date_logs_reverse(self, date:str, n_line:int=None):
        log_path = self._date_log_path(date)
        if log_path:
            return read_file_reverse(log_path, n_line)
        raise DbExecption(error("date not find", 404, False)) from None

    def delete_date_logs(self, date:str):
        if not self._log_path:
            raise DbExecption(error("log not instanciated", 404, False)) from None
        if date == date_cls.today().isoformat():
            raise DbExecption(error("log with date is using now", 400, False)) from None
        log_path = self._date_log_path(date)
        if log_path:
            log_path.unlink()
            return True
        raise DbExecption(error("date not find", 404, False)) from None