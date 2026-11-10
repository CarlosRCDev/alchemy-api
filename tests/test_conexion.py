from datetime import date, datetime

import pytest

from alchemy_api import Conexion
from alchemy_api.utils import DbException


def names(rows):
    return [r["name"] for r in rows]


def test_tables(cnx):
    tables, views = cnx.tables()
    assert tables == ["users"]
    assert views == []


def test_select_all(cnx):
    assert names(cnx.select("users", orderby={"id": False})) == ["ana", "luis", "marta", "pepa"]


def test_select_colset(cnx):
    assert cnx.select("users", colset=["name"], filterby={"id": 1}) == [{"name": "ana"}]


def test_select_count(cnx):
    assert list(cnx.select("users", count=True, filterby={"age": 30}).values()) == [2]


def test_select_unknown_table(cnx):
    with pytest.raises(DbException):
        cnx.select("nope")


def test_select_unknown_filter_column_raises(cnx):
    with pytest.raises(DbException):
        cnx.select("users", filterby={"typo": 1})


@pytest.mark.parametrize("cond, expected", [
    ({"type": ">", "value": 29}, ["ana", "marta", "pepa"]),
    ({"type": "<=", "value": 30}, ["ana", "luis", "marta"]),
    ({"type": "!=", "value": 30}, ["luis", "pepa"]),
    ({"type": "in", "value": [25, 40]}, ["luis", "pepa"]),
    ({"type": "between", "value1": 26, "value2": 35}, ["ana", "marta"]),
])
def test_filter_operators(cnx, cond, expected):
    rows = cnx.select("users", filterby={"age": cond}, orderby={"id": False})
    assert names(rows) == expected


def test_filter_startswith_endswith(cnx):
    assert names(cnx.select("users", filterby={"name": {"type": "startswith", "value": "ma"}})) == ["marta"]
    assert names(cnx.select("users", filterby={"name": {"type": "endswith", "value": "a"}}, orderby={"id": False})) == ["ana", "marta", "pepa"]


def test_filter_list_or(cnx):
    filterby = [{"key": "name", "conditions": ["ana", "pepa"], "and": False}]
    assert names(cnx.select("users", filterby=filterby, orderby={"id": False})) == ["ana", "pepa"]


def test_filter_invalid_type_raises(cnx):
    with pytest.raises(DbException):
        cnx.select("users", filterby={"age": {"type": "??", "value": 1}})


def test_filter_invalid_type_no_raise_is_ignored(cnx_no_raise):
    assert len(cnx_no_raise.select("users", filterby={"age": {"type": "??", "value": 1}})) == 4


def test_orderby_multiple_columns(cnx):
    # age desc, then id asc for ties
    rows = cnx.select("users", orderby={"age": True, "id": False})
    assert names(rows) == ["pepa", "ana", "marta", "luis"]


def test_offset_limit(cnx):
    rows = cnx.select("users", orderby={"id": False}, offset=1, limit=2)
    assert names(rows) == ["luis", "marta"]


def test_send_colnames_false(cnx):
    assert cnx.select("users", colset=["id", "name"], filterby={"id": 2}, send_colnames=False) == [[2, "luis"]]


def test_insert_with_datetime(cnx):
    data = {"id": 10, "name": "nuevo", "age": 1, "created": {"value": "2026-01-02 03:04", "dt_format": "%Y-%m-%d %H:%M"}}
    assert cnx.insert("users", data) == 1
    # The input is not modified: dt_format is converted on a copy
    assert data["created"] == {"value": "2026-01-02 03:04", "dt_format": "%Y-%m-%d %H:%M"}
    row = cnx.select("users", filterby={"id": 10}, dt_format="%Y-%m-%d %H:%M")
    assert row[0]["created"] == "2026-01-02 03:04"


def test_update_with_filter(cnx):
    result = cnx.update("users", {"age": 99}, filterby={"name": "luis"})
    assert result == 1
    assert cnx.select("users", filterby={"id": 2})[0]["age"] == 99


def test_update_without_filter_is_refused(cnx):
    with pytest.raises(DbException):
        cnx.update("users", {"age": 0})
    assert len(cnx.select("users", filterby={"age": 0})) == 0


def test_update_unknown_column_message(cnx):
    with pytest.raises(DbException, match="typo"):
        cnx.update("users", {"age": 0}, filterby={"typo": 1})


def test_delete_with_filter(cnx):
    assert cnx.delete("users", filterby={"id": 1}) == 1
    assert len(cnx.select("users")) == 3


def test_delete_without_filter_is_refused(cnx):
    with pytest.raises(DbException):
        cnx.delete("users", filterby={})
    assert len(cnx.select("users")) == 4


def test_delete_unknown_column_no_raise_does_not_wipe_table(cnx_no_raise):
    with pytest.raises(DbException):
        cnx_no_raise.delete("users", filterby={"typo": 1})
    assert len(cnx_no_raise.select("users")) == 4


def test_update_unknown_column_no_raise_does_not_touch_table(cnx_no_raise):
    with pytest.raises(DbException):
        cnx_no_raise.update("users", {"age": 0}, filterby={"typo": 1})
    assert len(cnx_no_raise.select("users", filterby={"age": 0})) == 0


def test_exec_sql(cnx):
    rows = cnx.exec_sql("SELECT name FROM users WHERE age = :age ORDER BY id", ret=True, bind={"age": 30})
    assert rows == [{"name": "ana"}, {"name": "marta"}]


def test_exec_sql_error_is_dbexception(cnx):
    with pytest.raises(DbException):
        cnx.exec_sql("SELECT * FROM missing_table", ret=True)


def test_lower_cols_modifier(cnx_cfg):
    from alchemy_api import Conexion
    cnx = Conexion(**cnx_cfg, modifiers={"lower_table": True, "lower_cols": True, "ret_upper_cols": True})
    rows = cnx.select("USERS", colset=["NAME"], filterby={"ID": 1})
    assert rows == [{"NAME": "ana"}]


def test_show_query_prints_to_console(cnx_cfg, capsys):
    from alchemy_api import Conexion
    cnx = Conexion(**cnx_cfg, show_query=True)
    cnx.select("users", filterby={"id": 1})
    cnx.insert("users", {"id": 20, "name": "x", "age": 1})
    out = capsys.readouterr().out
    assert "SELECT" in out and "INSERT" in out


def test_queries_in_file_log_only_with_debug(tmp_path, capsys):
    from alchemy_api import Conexion
    for level, logged in (("INFO", False), ("DEBUG", True)):
        log_path = tmp_path / f"{level}.log"
        cnx = Conexion(f"sqlite:///{tmp_path / 'q.db'}", config_log={"log_path": log_path, "level_log": level})
        cnx.exec_sql("SELECT 1")
        cnx.logger.handlers[0].flush()
        assert ("SELECT 1" in log_path.read_text()) is logged
    # Without show_query nothing goes to the console
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("log_name, rotated_name", [
    ("app.log", "app.2000-01-0{}.log"),
    ("app", "app.2000-01-0{}.log"),
])
def test_rotated_log_names(tmp_path, log_name, rotated_name):
    # Independent of the settings files: rotation must not touch the logs of the real config
    from alchemy_api import Conexion
    log_path = tmp_path / log_name
    for day in (1, 2, 3):
        (tmp_path / rotated_name.format(day)).write_text(f"day {day}\n", encoding="utf-8")
    (tmp_path / "other.2000-01-04.log").write_text("not mine\n", encoding="utf-8")
    cnx = Conexion("sqlite://", config_log={"log_path": log_path, "backup_count": 2})
    today = date.today().isoformat()
    assert cnx.list_logs() == ["2000-01-01", "2000-01-02", "2000-01-03", today]
    assert cnx.date_logs_order("2000-01-02") == ["day 2\n"]

    # Rollover keeps the extension after the date and removes the oldest beyond backup_count
    handler = cnx.logger.handlers[0]
    handler.doRollover()
    handler.close()
    assert (tmp_path / rotated_name.replace("2000-01-0{}", today)).is_file()
    assert not (tmp_path / rotated_name.format(1)).exists()
    assert (tmp_path / "other.2000-01-04.log").is_file()


def test_insert_many_rows(cnx):
    rows = [{"id": 100 + i, "name": f"n{i}", "age": i} for i in range(500)]
    assert cnx.insert("users", rows) == 500
    assert list(cnx.select("users", count=True).values()) == [504]


def test_insert_rows_with_different_columns(cnx):
    # executemany needs the same columns: rows are grouped, every row is inserted with its own columns
    rows = [
        {"id": 20, "name": "a", "age": 1},
        {"id": 21, "name": "b"},
        {"id": 22, "name": "c"},
        {"id": 23, "name": "d", "age": 4},
    ]
    assert cnx.insert("users", rows) == 4
    got = cnx.select("users", colset=["id", "age"], filterby={"id": {"type": ">=", "value": 20}}, orderby={"id": False})
    assert got == [{"id": 20, "age": 1}, {"id": 21, "age": None}, {"id": 22, "age": None}, {"id": 23, "age": 4}]


def test_insert_empty(cnx):
    assert cnx.insert("users", []) == 0


def test_insert_is_atomic(cnx):
    # id 1 already exists: the whole insert fails and no row is left
    with pytest.raises(DbException):
        cnx.insert("users", [{"id": 30, "name": "x", "age": 1}, {"id": 1, "name": "dup", "age": 1}])
    assert cnx.select("users", filterby={"id": 30}) == []


def test_insert_logs_once_per_group(cnx_cfg, capsys):
    from alchemy_api import Conexion
    cnx = Conexion(**{**cnx_cfg, "config_log": None}, show_query=True)
    cnx.insert("users", [{"id": 40 + i, "name": "x", "age": i} for i in range(50)])
    inserts = [line for line in capsys.readouterr().out.splitlines() if "INSERT" in line]
    assert len(inserts) == 1 and "first of 50 rows" in inserts[0]


def test_offset_without_orderby(cnx):
    # SQL Server needs ORDER BY for OFFSET: the primary key is used when there is no orderby
    rows = cnx.select("users", offset=1)
    assert len(rows) == 3


def test_schema(cnx):
    schema = cnx.schema("users")
    columns = {col["name"]: col for col in schema["columns"]}
    assert set(columns) == {"id", "name", "age", "created"}
    assert columns["id"]["primary_key"] is True
    assert columns["id"]["nullable"] is False
    assert columns["name"]["primary_key"] is False
    assert "CHAR" in columns["name"]["type"].upper()
    assert schema["foreign_keys"] == []


def test_schema_unknown_table(cnx):
    with pytest.raises(DbException):
        cnx.schema("missing")


@pytest.mark.parametrize("modifiers, column, references", [
    ({}, "user_id", "users.id"),
    ({"ret_upper_cols": True}, "USER_ID", "users.ID"),
    ({"ret_upper_table": True}, "user_id", "USERS.id"),
    ({"ret_upper_cols": True, "ret_upper_table": True}, "USER_ID", "USERS.ID"),
])
def test_schema_modifiers(cnx_cfg, orders_table, modifiers, column, references):
    schema = Conexion(**cnx_cfg, modifiers=modifiers).schema("orders")
    assert column in [col["name"] for col in schema["columns"]]
    assert [column] in [idx["columns"] for idx in schema["indexes"]]
    assert schema["foreign_keys"] == [{"column": column, "references": references}]


def test_join_inner(cnx_orders):
    rows = cnx_orders.select(
        "users", colset=["name", "orders.total"],
        join=[{"table": "orders", "type": "inner", "on": {"id": "user_id"}}],
        orderby={"orders.id": False},
    )
    assert rows == [{"name": "ana", "orders.total": 10}, {"name": "ana", "orders.total": 20}, {"name": "luis", "orders.total": 5}]


def test_join_left(cnx_orders):
    rows = cnx_orders.select(
        "users", colset=["name", "orders.total"],
        join={"table": "orders", "type": "left", "on": {"id": "user_id"}},
        orderby={"id": False, "orders.id": False},
    )
    assert [(r["name"], r["orders.total"]) for r in rows] == [("ana", 10), ("ana", 20), ("luis", 5), ("marta", None), ("pepa", None)]


def test_join_right(cnx_orders):
    # The order without user (id 4) is kept, with the users columns as NULL
    rows = cnx_orders.select(
        "users", colset=["name", "orders.id"],
        join=[{"table": "orders", "type": "right", "on": {"id": "user_id"}}],
        orderby={"orders.id": False},
    )
    assert rows == [
        {"name": "ana", "orders.id": 1}, {"name": "ana", "orders.id": 2},
        {"name": "luis", "orders.id": 3}, {"name": None, "orders.id": 4},
    ]


def test_join_foreign_key_and_default_columns(cnx_orders):
    # Without "on" the foreign key is used; without colset every column, joined ones as "table.column"
    rows = cnx_orders.select("users", join=[{"table": "orders"}], filterby={"orders.total": 5})
    assert len(rows) == 1
    assert {k: rows[0][k] for k in ("id", "name", "orders.id", "orders.user_id", "orders.total")} == {
        "id": 2, "name": "luis", "orders.id": 3, "orders.user_id": 2, "orders.total": 5,
    }
    assert set(rows[0]) == {"id", "name", "age", "created", "orders.id", "orders.user_id", "orders.total"}


def test_join_filter_count_offset_limit(cnx_orders):
    join = [{"table": "orders", "type": "left", "on": {"id": "user_id"}}]
    assert list(cnx_orders.select("users", join=join, count=True).values()) == [5]
    assert list(cnx_orders.select("users", join=join, count=True, filterby={"orders.total": {"type": ">", "value": 8}}).values()) == [2]
    # NULLs sort first or last depending on the backend: left out
    rows = cnx_orders.select(
        "users", colset=["orders.id"], join=join, filterby={"orders.id": {"type": "is_not", "value": None}},
        orderby={"orders.id": True}, offset=1, limit=2, send_colnames=False,
    )
    assert rows == [[2], [1]]


def test_join_from_joined_table(cnx_orders):
    # The base table can be the one with the foreign key; "on" keys can be "table.column"
    rows = cnx_orders.select(
        "orders", colset=["id", "users.name"],
        join=[{"table": "users", "type": "left", "on": {"orders.user_id": "users.id"}}],
        orderby={"id": False},
    )
    assert [r["users.name"] for r in rows] == ["ana", "ana", "luis", None]


@pytest.mark.parametrize("join", [
    "orders",
    [{"type": "inner"}],
    [{"table": "orders", "type": "full"}],
    [{"table": "orders", "type": "LEFT"}],
    [{"table": "orders", "how": "left"}],
    [{"table": "missing", "on": {"id": "user_id"}}],
    [{"table": "orders", "on": {"typo": "user_id"}}],
    [{"table": "orders", "on": {"id": "typo"}}],
    [{"table": "orders", "on": {}}],
    [{"table": "users", "on": {"id": "id"}}],
])
def test_join_invalid(cnx_orders, join):
    with pytest.raises(DbException):
        cnx_orders.select("users", join=join)


def test_join_on_unknown_column_raises_without_raise(cnx_cfg, orders_table):
    # A discarded "on" condition would join every row: always an error
    cnx = Conexion(**cnx_cfg, _raise=False)
    with pytest.raises(DbException):
        cnx.select("users", join=[{"table": "orders", "on": {"typo": "user_id"}}])


def test_join_unknown_column_raises(cnx_orders):
    with pytest.raises(DbException):
        cnx_orders.select("users", colset=["orders.typo"], join=[{"table": "orders"}])
    with pytest.raises(DbException):
        cnx_orders.select("users", filterby={"orders.typo": 1}, join=[{"table": "orders"}])


def test_join_modifiers(cnx_cfg, orders_table):
    cnx = Conexion(**cnx_cfg, modifiers={"lower_table": True, "lower_cols": True, "ret_upper_cols": True})
    rows = cnx.select(
        "USERS", colset=["NAME", "ORDERS.TOTAL"],
        join=[{"table": "ORDERS", "type": "inner", "on": {"ID": "USER_ID"}}],
        filterby={"ORDERS.TOTAL": 5},
    )
    assert rows == [{"NAME": "luis", "ORDERS.TOTAL": 5}]
