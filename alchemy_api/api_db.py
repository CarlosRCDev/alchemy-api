from flask import Blueprint, jsonify, request, make_response, current_app

from .utils import DbExecption, error
### FUNCTIONS ###
api_db = Blueprint("db", __name__, static_folder="static", template_folder="static")
api_log = Blueprint("log", __name__, static_folder="static", template_folder="static")
api_log_delete = Blueprint("delete_log", __name__, static_folder="static", template_folder="static")

"""--------------------------------------------------------------
|                       Metodos Generales                      |
--------------------------------------------------------------"""
#Metodos generales (select,insert,delete,update) incluidos para testing.

@api_db.app_errorhandler(Exception)
def error_handler(err):
    return make_response(jsonify(error=str(err)), 500)

@api_db.app_errorhandler(DbExecption)
def api_db_error(err):
    return make_response(
        jsonify(
            error=str(err),
            url=request.url
        ),
        getattr(err, "status_code") if getattr(err, "status_code") else 500)


@api_db.route('/select', methods=['POST'])
def select(db_data=None):
    if not db_data:
        db_data = request.json
    table = db_data.pop("table", None)

    if not table: raise DbExecption(error("Not table in post", 400)) from None
    result_db = current_app.config["CNX"].select(table=table, **db_data)

    return jsonify(result_db)

@api_db.route('/insert', methods=['POST'])
def insert():
    db_data = request.json
    table = db_data.pop("table", None)
    data = db_data.pop("data", None)
    
    if not table: raise DbExecption(error("Not table in post", 400)) from None
    if not data: raise DbExecption(error("Not data in post", 400)) from None

    result_db = current_app.config["CNX"].insert(table=table, data=data)
    
    return jsonify(insert = sum(map(lambda x: x.is_insert, result_db)))

@api_db.route('/delete', methods=['POST'])
def delete():
    db_data = request.json
    table = db_data.pop("table", None)
    filterby = db_data.pop("filterby", None)
    
    if not table: raise DbExecption(error("Not table in post", 400)) from None
    if not filterby: raise DbExecption(error("Not filterby in post", 400)) from None
    result_db = current_app.config["CNX"].delete(table=table, filterby=filterby)

    return jsonify(delete=result_db.rowcount)

@api_db.route('/update', methods=['POST'])
def update():
    db_data = request.json
    table = db_data.pop("table", None)
    data = db_data.pop("data", None)

    if not table: raise DbExecption(error("Not table in post", 400)) from None
    if not data: raise DbExecption(error("Not data in post", 400)) from None
    if not db_data.get("filterby"): raise DbExecption(error("Not filterby in post", 400)) from None
    
    result_db = current_app.config["CNX"].update(table=table, data=data, **db_data)
    
    return jsonify(update=result_db.rowcount)

@api_db.route('/tables', methods=['GET'])
def tables():

    tables, views = current_app.config["CNX"].tables()
    
    return jsonify(tables=tables, views=views)

@api_db.route('/schema', methods=['POST'])
def schema():
    db_data = request.json
    table = db_data.get("table", None)

    if not table: raise DbExecption(error("Not data in post", 400)) from None
    schema = current_app.config["CNX"].schema(table)

    return jsonify(schema)

@api_db.route('/sql', methods=['POST'])
def sql():
    # Raw SQL is only allowed when the app enables it explicitly
    if not current_app.config.get("DB_ALLOW_RAW_SQL", False):
        raise DbExecption(error("Endpoint /sql disabled, set DB_ALLOW_RAW_SQL in app config", 403)) from None
    db_data = request.json
    statement = db_data.get("statement", None)
    if not statement: raise DbExecption(error("Not statement in post", 400)) from None
    parameters = db_data.get("parameters", {})

    ret = db_data.get("ret", False)
    if not isinstance(db_data.get("ret", False), bool):
        raise DbExecption(error(f"Not valid ret in post, must be boolean, value: {db_data.get("ret", None)}", 400)) from None

    result_db = current_app.config["CNX"].exec_sql(statement=statement, ret=ret, bind=parameters)
    if ret:
        return jsonify(result_db)
    else:
        return make_response(jsonify(result_db), 204)

    
@api_log.route("",  methods=["GET"])
def log_list():
    return jsonify(current_app.config["CNX"].list_logs())

@api_log.route("/order/<date>",  methods=["GET"])
def log_date_order(date, n_line=None):
    return jsonify(current_app.config["CNX"].date_logs_order(date))

@api_log.route("/reverse/<date>/<n_line>",  methods=["GET"])
@api_log.route("/reverse/<date>",  methods=["GET"])
def log_date_reverse(date, n_line=None):
    if n_line:
        try:
            n_line = int(n_line)
        except ValueError:
            raise DbExecption(error(f"Not valid n_line in URL, must be integer, value: {n_line}", 400)) from None
    return jsonify(current_app.config["CNX"].date_logs_reverse(date, n_line))

@api_log_delete.route("/<date>",  methods=["DELETE"])
def delete_date(date):
    current_app.config["CNX"].delete_date_logs(date)
    return jsonify(msg=f"Removed log: {date}")