"""Demo table shared by the examples: users(id, name, age, created)"""
import json
from os import getenv
from pathlib import Path
import warnings

from alchemy_api.permissions import read_permissions
from alchemy_api.utils import DbException, read_cnx_data

# Settings file from the CONFIG_FILE env var, e.g. CONFIG_FILE=tests/settings/config_oracle.json
CONFIG_FILE = Path(getenv("CONFIG_FILE", Path(__file__).resolve().parent / "config.json"))

ROWS = [
    {"id": 1, "name": "ana", "age": 30},
    {"id": 2, "name": "luis", "age": 25},
    {"id": 3, "name": "marta", "age": 30},
]


def load_config(config_file=CONFIG_FILE):
    """settings json -> Conexion kwargs"""
    with open(config_file) as f:
        cfg = json.load(f)["database"]
    if cfg.get("type") == "sqlite":
        Path(cfg["path"]).parent.mkdir(parents=True, exist_ok=True)
    cnx_data, cnx_data_extra, show_query, modifiers, config_log = read_cnx_data(cfg)
    return {
        "cnx_data": cnx_data,
        "cnx_data_extra": cnx_data_extra,
        "show_query": show_query,
        "modifiers": modifiers,
        "config_log": config_log,
    }


def load_permissions(config_file=CONFIG_FILE):
    """"permissions" section of the settings json -> (roles, tables), each None without that control"""
    with open(config_file) as f:
        return read_permissions(json.load(f).get("permissions"))


# Demo only: api key -> role. A real app validates a token (JWT, OAuth2, ...) or looks the key up in a store
API_KEYS = {"admin-key": "admin", "editor-key": "editor", "reader-key": "reader"}
API_KEY_HEADER = "X-API-Key"


def get_role(request):
    """Role of the request from the API_KEY_HEADER header (works with Flask and FastAPI requests)"""
    return API_KEYS.get(request.headers.get(API_KEY_HEADER))


def create_demo_table(cnx):
    """Creates and fills the users table if it does not exist yet; only warns if it can not"""
    tables, _ = cnx.tables()
    # Case insensitive: with ret_upper_table (Oracle settings) tables() returns "USERS"
    if "users" in (table.lower() for table in tables):
        warnings.warn("Table users already exists, demo data not created", stacklevel=2)
        return
    try:
        cnx.exec_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(50), age INTEGER, created TIMESTAMP)")
        # Conexion reflects the tables when it is created, so it has to reload them
        cnx.post_conexion()
        cnx.insert("users", ROWS)
    except DbException as e:
        # e.g. READ_ONLY connection or no CREATE grant: the api starts anyway
        warnings.warn(f"Demo table users not created: {e}", stacklevel=2)
