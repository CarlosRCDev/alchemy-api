from datetime import date, datetime

import pytest

from alchemy_api.utils import DbExecption


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
    with pytest.raises(DbExecption):
        cnx.select("nope")


def test_select_unknown_filter_column_raises(cnx):
    with pytest.raises(DbExecption):
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
    with pytest.raises(DbExecption):
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
    result = cnx.insert("users", data)
    assert len(result) == 1
    row = cnx.select("users", filterby={"id": 10}, dt_format="%Y-%m-%d %H:%M")
    assert row[0]["created"] == "2026-01-02 03:04"


def test_update_with_filter(cnx):
    result = cnx.update("users", {"age": 99}, filterby={"name": "luis"})
    assert result.rowcount == 1
    assert cnx.select("users", filterby={"id": 2})[0]["age"] == 99


def test_update_without_filter_is_refused(cnx):
    with pytest.raises(DbExecption):
        cnx.update("users", {"age": 0})
    assert len(cnx.select("users", filterby={"age": 0})) == 0


def test_update_unknown_column_message(cnx):
    with pytest.raises(DbExecption, match="typo"):
        cnx.update("users", {"age": 0}, filterby={"typo": 1})


def test_delete_with_filter(cnx):
    assert cnx.delete("users", filterby={"id": 1}).rowcount == 1
    assert len(cnx.select("users")) == 3


def test_delete_without_filter_is_refused(cnx):
    with pytest.raises(DbExecption):
        cnx.delete("users", filterby={})
    assert len(cnx.select("users")) == 4


def test_delete_unknown_column_no_raise_does_not_wipe_table(cnx_no_raise):
    with pytest.raises(DbExecption):
        cnx_no_raise.delete("users", filterby={"typo": 1})
    assert len(cnx_no_raise.select("users")) == 4


def test_update_unknown_column_no_raise_does_not_touch_table(cnx_no_raise):
    with pytest.raises(DbExecption):
        cnx_no_raise.update("users", {"age": 0}, filterby={"typo": 1})
    assert len(cnx_no_raise.select("users", filterby={"age": 0})) == 0


def test_exec_sql(cnx):
    rows = cnx.exec_sql("SELECT name FROM users WHERE age = :age ORDER BY id", ret=True, bind={"age": 30})
    assert rows == [{"name": "ana"}, {"name": "marta"}]


def test_exec_sql_error_is_dbexception(cnx):
    with pytest.raises(DbExecption):
        cnx.exec_sql("SELECT * FROM missing_table", ret=True)


def test_lower_cols_modifier(cnx_cfg):
    from alchemy_api import Conexion
    cnx = Conexion(**cnx_cfg, modifiers={"lower_table": True, "lower_cols": True, "ret_upper_cols": True})
    rows = cnx.select("USERS", colset=["NAME"], filterby={"ID": 1})
    assert rows == [{"NAME": "ana"}]


def test_show_query_does_not_break(cnx_cfg, caplog):
    from alchemy_api import Conexion
    # Without config_log: the file logger does not propagate, so caplog would not see it
    cnx = Conexion(**{**cnx_cfg, "config_log": None}, show_query=True)
    with caplog.at_level("INFO"):
        cnx.select("users", filterby={"id": 1})
        cnx.insert("users", {"id": 20, "name": "x", "age": 1})
    assert any("SELECT" in r.message for r in caplog.records)


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
