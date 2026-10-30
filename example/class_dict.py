"""Conexion class without a REST api, configured with a python dict

Run from the project root:
    PYTHONPATH=. uv run python example/class_dict.py
"""
from pathlib import Path

from alchemy_api import Conexion
from alchemy_api.utils import read_cnx_data
from demo_data import create_demo_table

HERE = Path(__file__).resolve().parent

# Same keys as the "database" block of the settings json
config = {
    "type": "sqlite",
    "path": HERE / "db" / "example_dict.db",
    "show_query": False,
    "log": {
        "path": HERE / "logdb" / "example_dict.log",
        "level_log": "DEBUG",
        "backup_count": 10,
    },
}
config["path"].parent.mkdir(parents=True, exist_ok=True)

cnx_data, cnx_data_extra, show_query, modifiers, config_log = read_cnx_data(config)
cnx = Conexion(
    cnx_data,
    cnx_data_extra=cnx_data_extra,
    show_query=show_query,
    modifiers=modifiers,
    config_log=config_log,
)
create_demo_table(cnx)

print("tables:", cnx.tables())
print("schema:", cnx.schema("users"))
print("all:", cnx.select("users", orderby={"id": False}))
print("age 30:", cnx.select("users", colset=["name"], filterby={"age": 30}))
print("age > 26:", cnx.select("users", filterby={"age": {"type": ">", "value": 26}}))
print("count:", cnx.select("users", count=True))

cnx.insert("users", [{"id": 10, "name": "pepa", "age": 40}])
print("updated:", cnx.update("users", {"age": 41}, filterby={"id": 10}).rowcount)
print("pepa:", cnx.select("users", filterby={"id": 10}))
print("deleted:", cnx.delete("users", filterby={"id": 10}).rowcount)

print("sql:", cnx.exec_sql("SELECT name FROM users WHERE age = :age", ret=True, bind={"age": 25}))
print("logs:", cnx.list_logs())
