"""REST api with Flask

Run from the project root:
    PYTHONPATH=. uv run python example/api_flask.py

Try it (orderby {"col": true} is descending, false ascending):
    curl http://127.0.0.1:5000/db/tables
    curl -X POST http://127.0.0.1:5000/db/select -H "Content-Type: application/json" \
         -d '{"table": "users", "filterby": {"age": 30}, "orderby": {"name": true}}'
    curl -X POST http://127.0.0.1:5000/db/insert -H "Content-Type: application/json" \
         -d '{"table": "users", "data": [{"id": 10, "name": "pepa", "age": 40}]}'
    curl http://127.0.0.1:5000/log
"""
from flask import Flask

from alchemy_api import Conexion
from alchemy_api.api_db import api_db, api_log, api_log_delete
from demo_data import create_demo_table, load_config

cnx = Conexion(**load_config())
create_demo_table(cnx)

app = Flask(__name__)
# The blueprints read the connection from app.config["CNX"]
app.config["CNX"] = cnx
# /db/sql is disabled unless this is True
app.config["DB_ALLOW_RAW_SQL"] = False
app.register_blueprint(api_db, url_prefix="/db")
app.register_blueprint(api_log, url_prefix="/log")
app.register_blueprint(api_log_delete, url_prefix="/delete_log")


if __name__ == "__main__":
    app.run(debug=True)
