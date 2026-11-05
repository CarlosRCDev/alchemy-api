from functools import wraps

from flask import Blueprint, jsonify, request, make_response, current_app, g

from .permissions import check_permission, check_table, filter_tables
from .utils import DbException, error
### FUNCTIONS ###
# Connection in app.config["CNX"]. Optional permissions (operations and tables per role):
#   app.config["DB_ROLES"], app.config["DB_TABLES"] = read_permissions(settings.get("permissions"))
#   app.config["DB_GET_ROLE"] = get_role  # get_role(request) -> role name or None
api_db = Blueprint("db", __name__, static_folder="static", template_folder="static")
api_log = Blueprint("log", __name__, static_folder="static", template_folder="static")
api_log_delete = Blueprint("delete_log", __name__, static_folder="static", template_folder="static")

"""--------------------------------------------------------------
|                       Metodos Generales                      |
--------------------------------------------------------------"""
#Metodos generales (select,insert,delete,update) incluidos para testing.

def require(operation):
    """Checks the role of the request against app.config["DB_ROLES"] before the endpoint"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            roles = current_app.config.get("DB_ROLES")
            tables = current_app.config.get("DB_TABLES")
            get_role = current_app.config.get("DB_GET_ROLE")
            needs_role = roles is not None or tables is not None
            # Resolved once per request, _check_table reuses it
            g.db_role = get_role(request) if needs_role and get_role else None
            check_permission(roles, get_role, g.db_role, operation)
            return func(*args, **kwargs)
        return wrapper
    return decorator

def _check_table(table):
    """Checks the table against app.config["DB_TABLES"]. table=None needs every table (raw SQL)"""
    check_table(current_app.config.get("DB_TABLES"), current_app.config.get("DB_GET_ROLE"), g.get("db_role"), table)

@api_db.app_errorhandler(Exception)
def error_handler(err):
    return make_response(jsonify(error=str(err)), 500)

@api_db.app_errorhandler(DbException)
def api_db_error(err):
    return make_response(
        jsonify(
            error=str(err),
            url=request.url
        ),
        getattr(err, "status_code") if getattr(err, "status_code") else 500)


@api_db.route('/select', methods=['POST'])
@require("select")
def select(db_data=None):
    if not db_data:
        db_data = request.json
    table = db_data.pop("table", None)

    if not table: raise DbException(error("Not table in post", 400)) from None
    _check_table(table)
    result_db = current_app.config["CNX"].select(table=table, **db_data)

    return jsonify(result_db)

@api_db.route('/insert', methods=['POST'])
@require("insert")
def insert():
    db_data = request.json
    table = db_data.pop("table", None)
    data = db_data.pop("data", None)
    
    if not table: raise DbException(error("Not table in post", 400)) from None
    _check_table(table)
    if not data: raise DbException(error("Not data in post", 400)) from None

    result_db = current_app.config["CNX"].insert(table=table, data=data)
    
    return jsonify(insert=result_db)

@api_db.route('/delete', methods=['POST'])
@require("delete")
def delete():
    db_data = request.json
    table = db_data.pop("table", None)
    filterby = db_data.pop("filterby", None)
    
    if not table: raise DbException(error("Not table in post", 400)) from None
    _check_table(table)
    if not filterby: raise DbException(error("Not filterby in post", 400)) from None
    result_db = current_app.config["CNX"].delete(table=table, filterby=filterby)

    return jsonify(delete=result_db)

@api_db.route('/update', methods=['POST'])
@require("update")
def update():
    db_data = request.json
    table = db_data.pop("table", None)
    data = db_data.pop("data", None)

    if not table: raise DbException(error("Not table in post", 400)) from None
    _check_table(table)
    if not data: raise DbException(error("Not data in post", 400)) from None
    if not db_data.get("filterby"): raise DbException(error("Not filterby in post", 400)) from None
    
    result_db = current_app.config["CNX"].update(table=table, data=data, **db_data)
    
    return jsonify(update=result_db)

@api_db.route('/tables', methods=['GET'])
@require("tables")
def tables():

    tables, views = current_app.config["CNX"].tables()
    # Only what the role can use when there are table permissions
    allowed = current_app.config.get("DB_TABLES")
    get_role = current_app.config.get("DB_GET_ROLE")
    tables = filter_tables(allowed, get_role, g.get("db_role"), tables)
    views = filter_tables(allowed, get_role, g.get("db_role"), views)

    return jsonify(tables=tables, views=views)

@api_db.route('/schema', methods=['POST'])
@require("schema")
def schema():
    db_data = request.json
    table = db_data.get("table", None)

    if not table: raise DbException(error("Not data in post", 400)) from None
    _check_table(table)
    schema = current_app.config["CNX"].schema(table)

    return jsonify(schema)

@api_db.route('/sql', methods=['POST'])
@require("sql")
def sql():
    # Raw SQL is only allowed when the app enables it explicitly
    if not current_app.config.get("DB_ALLOW_RAW_SQL", False):
        raise DbException(error("Endpoint /sql disabled, set DB_ALLOW_RAW_SQL in app config", 403)) from None
    # Raw SQL can touch any table: only roles with "tables": ["*"]
    _check_table(None)
    db_data = request.json
    statement = db_data.get("statement", None)
    if not statement: raise DbException(error("Not statement in post", 400)) from None
    parameters = db_data.get("parameters", {})

    ret = db_data.get("ret", False)
    if not isinstance(db_data.get("ret", False), bool):
        raise DbException(error(f"Not valid ret in post, must be boolean, value: {db_data.get("ret", None)}", 400)) from None

    result_db = current_app.config["CNX"].exec_sql(statement=statement, ret=ret, bind=parameters)
    if ret:
        return jsonify(result_db)
    else:
        return make_response(jsonify(result_db), 204)

    
@api_log.route("",  methods=["GET"])
@require("log_read")
def log_list():
    return jsonify(current_app.config["CNX"].list_logs())

@api_log.route("/order/<date>",  methods=["GET"])
@require("log_read")
def log_date_order(date, n_line=None):
    return jsonify(current_app.config["CNX"].date_logs_order(date))

@api_log.route("/reverse/<date>/<n_line>",  methods=["GET"])
@api_log.route("/reverse/<date>",  methods=["GET"])
@require("log_read")
def log_date_reverse(date, n_line=None):
    if n_line:
        try:
            n_line = int(n_line)
        except ValueError:
            raise DbException(error(f"Not valid n_line in URL, must be integer, value: {n_line}", 400)) from None
    return jsonify(current_app.config["CNX"].date_logs_reverse(date, n_line))

@api_log_delete.route("/<date>",  methods=["DELETE"])
@require("log_delete")
def delete_date(date):
    current_app.config["CNX"].delete_date_logs(date)
    return jsonify(msg=f"Removed log: {date}")