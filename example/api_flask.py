"""REST api with Flask

Run from the project root:
    uv run python example/api_flask.py
Other settings file (default example/config.json):
    CONFIG_FILE=tests/settings/config_oracle.json uv run python example/api_flask.py

Try it (orderby {"col": true} is descending, false ascending):
    curl http://127.0.0.1:5000/db/tables -H "X-API-Key: reader-key"
    curl -X POST http://127.0.0.1:5000/db/select -H "X-API-Key: reader-key" -H "Content-Type: application/json" \
         -d '{"table": "users", "filterby": {"age": 30}, "orderby": {"name": true}}'
    # reader-key gets 403 here, editor-key or admin-key can insert
    curl -X POST http://127.0.0.1:5000/db/insert -H "X-API-Key: editor-key" -H "Content-Type: application/json" \
         -d '{"table": "users", "data": [{"id": 10, "name": "pepa", "age": 40}]}'
    curl http://127.0.0.1:5000/log -H "X-API-Key: admin-key"
"""
from flask import Flask

from alchemy_api import Conexion
from alchemy_api.api_db import api_db, api_log, api_log_delete
from demo_data import create_demo_table, get_role, load_config, load_permissions

cnx = Conexion(**load_config())
create_demo_table(cnx)

app = Flask(__name__)
# The blueprints read the connection from app.config["CNX"]
app.config["CNX"] = cnx
# /db/sql is disabled unless this is True
app.config["DB_ALLOW_RAW_SQL"] = False
# Operations and tables per role, "permissions" section of the settings file (None: no control)
app.config["DB_ROLES"], app.config["DB_TABLES"] = load_permissions()
app.config["DB_GET_ROLE"] = get_role
app.register_blueprint(api_db, url_prefix="/db")
app.register_blueprint(api_log, url_prefix="/log")
app.register_blueprint(api_log_delete, url_prefix="/delete_log")


if __name__ == "__main__":
    app.run(debug=True)
