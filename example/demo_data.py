"""Demo table shared by the examples: users(id, name, age, created)"""
import json
from pathlib import Path

from alchemy_api.utils import read_cnx_data

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"

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


def create_demo_table(cnx):
    """Creates and fills the users table if it does not exist yet"""
    tables, _ = cnx.tables()
    if "users" in tables:
        return
    cnx.exec_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(50), age INTEGER, created TIMESTAMP)")
    # Conexion reflects the tables when it is created, so it has to reload them
    cnx.post_conexion()
    cnx.insert("users", ROWS)
