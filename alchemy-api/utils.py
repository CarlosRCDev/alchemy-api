from collections import namedtuple
from os import getenv
from sqlalchemy.engine.row import Row
from sqlalchemy.engine.cursor import CursorResult

class DbExecption(Exception):
    def __init__(self, rsp):
        self.args = (rsp.text,)
        self.status_code = rsp.status_code
        if getattr(rsp, "trace") is False:
            self.trace = None
    
    def __str__(self) -> str:
        return ", ".join(self.args)

error = namedtuple(
    "error",
    "text status_code trace",
    defaults=[400, None]
    )

def read_cnx_data(cfg_data):
    type_ = cfg_data.get("type", getenv("DB_TYPE"))
    show_query = cfg_data.get('show_query', getenv("DB_SHOW_QUERY", False))
    modifiers = cfg_data.get("modifiers", {})
    cnx_data_extra = cfg_data.get("cnx_data_extra", {})
    if type_ == "oracle":
        server = cfg_data.get("server", getenv("DB_SERVER"))
        port = cfg_data.get("port", getenv("DB_PORT"))
        sid = cfg_data.get("sid", getenv("DB_SID"))
        user = cfg_data.get("user", getenv("DB_USER"))
        password = cfg_data.get("password", getenv("DB_PASSWORD"))
        dsn = cfg_data.get("dsn", getenv("DB_DSN"))
        thick_mode = cfg_data.pop("thick_mode", False)
        service_name = cfg_data.pop("service_name", getenv("DB_SERVICE_NAME"))
        if not dsn:
            from oracledb import makedsn
            dsn = makedsn(server, port, sid=sid, service_name=service_name)
        else:
            from oracledb import is_thin_mode
            if thick_mode:
                from oracledb import init_oracle_client
                init_oracle_client()
            print(f"Thick mode: {not is_thin_mode()}")
        cnx_data = f"oracle+oracledb://{user}:{password}@{dsn}"
    elif type_ == "mariadb":
        server = cfg_data.get("server", getenv("DB_SERVER"))
        port = cfg_data.get("port", getenv("DB_PORT"))
        user = cfg_data.get("user", getenv("DB_USER"))
        password = cfg_data.get("password", getenv("DB_PASSWORD"))
        db = cfg_data.get("db", getenv("DB_DB"))
        cnx_data = f"mariadb+pymysql://{user}:{password}@{server}:{port}/{db}?charset=utf8"
    elif type_ == "async_mariadb":
        server = cfg_data.get("server", getenv("DB_SERVER"))
        port = cfg_data.get("port", getenv("DB_PORT"))
        user = cfg_data.get("user", getenv("DB_USER"))
        password = cfg_data.get("password", getenv("DB_PASSWORD"))
        db = cfg_data.get("db", getenv("DB_DB"))
        cnx_data = f"mariadb+aiomysql://{user}:{password}@{server}:{port}/{db}?charset=utf8"    
    elif type_ == "sqlite":
        path = cfg_data.get("path", getenv("DB_PATH"))
        cnx_data = f"sqlite:///{path}"
    elif type_ == "psycopg":
        server = cfg_data.get("server", getenv("DB_SERVER"))
        port = cfg_data.get("port", getenv("DB_PORT"))
        user = cfg_data.get("user", getenv("DB_USER"))
        password = cfg_data.get("password", getenv("DB_PASSWORD"))
        db = cfg_data.get("db", getenv("DB_DB"))
        cnx_data = f"postgresql+psycopg://{user}:{password}@{server}:{port}/{db}"
    else:
        raise DbExecption(error(f"Not valid type: {type_}", 400)) from None
    _config_log = cfg_data.get("log", {})
    config_log = {}
    if _config_log:
        config_log.setdefault("level_log", _config_log.get("level_log", "INFO"))
        config_log.setdefault("log_path", _config_log.get("path", None))
        try:
            backup_count = int(_config_log.get("backup_count", 10))
        except Exception as e:
            print(repr(Warning(f"backup_count, fails not integer, value: {_config_log.get('backup_count')}, set default value = 10", str(e))))
            backup_count = 10
        config_log.setdefault("backup_count", backup_count)
    
    if not config_log.get("log_path"):
        config_log = {}    
    
    return cnx_data, cnx_data_extra, show_query, modifiers, config_log

def to_dict(obj):
    """
    Transform SQLAlhemy return to list of dict

    Parameters
    -----------
    obj:
        list of LegacyRow or LegacyRow
    
    Returns
    ---------
    list(dict):
        SQL columns and data
    """
    if obj is None: return []
    elif isinstance(obj, list): return [to_dict(i)[0] for i in obj]
    elif isinstance(obj, Row): return [obj._asdict()]
    else: raise TypeError("Not Row, type:" + str(type(obj)))
    
def _read_file_reverse(file_path):
    with open(file_path, 'rb') as f:
        buffer_size = 8192  # Size of chunks to read
        f.seek(0, 2)  # Go to the end of the file
        end_of_file = f.tell()
        buffer = bytearray()
        pointer_location = end_of_file
 
        while pointer_location > 0:
            pointer_location = max(0, pointer_location - buffer_size)
            f.seek(pointer_location)
            buffer.extend(f.read(min(buffer_size, end_of_file - pointer_location)))
            lines = buffer.split(b'\n')
            
            # Reverse iterate over the lines
            if pointer_location > 0:
                # The last line in the buffer might be incomplete, keep it for the next chunk
                buffer = lines[0]
                lines = lines[1:]
            else:
                buffer = bytearray()
 
            for line in reversed(lines):
                yield line.decode('utf-8')
 
        # Yield the remaining buffered line if any
        if buffer:
            yield buffer.decode('utf-8')

def read_file_reverse(file_path:str, n_line:int=None):
    lines = []
    n_line = n_line or -1
    for idx, line in enumerate(_read_file_reverse(file_path)):
        if line:
            lines.append(line)
        if idx == n_line:
            break
    return lines

def return_inserted(result_db):
    if isinstance(result_db, list):
        _result_db = []
        for result in result_db:
            _result_db.append(return_inserted(result))
        return _result_db
    elif isinstance(result_db, CursorResult):
        return result_db.returned_defaults._asdict() if result_db.returned_defaults else result_db.inserted_primary_key._asdict() if result_db.inserted_primary_key else {}
    else:
        return {}
