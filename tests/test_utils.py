import pytest

from alchemy_api.utils import DbException, error, read_cnx_data, read_file_reverse


def test_read_file_reverse_across_chunks(tmp_path):
    # Lines long enough to cross several 8192-byte chunks
    expected = [f"line-{i:05d}-" + "x" * 50 for i in range(500)]
    path = tmp_path / "file.log"
    path.write_text("\n".join(expected) + "\n", encoding="utf-8")
    assert read_file_reverse(path) == expected[::-1]


def test_read_file_reverse_n_line(tmp_path):
    path = tmp_path / "file.log"
    path.write_text("a\nb\nc\n", encoding="utf-8")
    assert read_file_reverse(path, 2) == ["c", "b"]


def test_dbexception():
    exc = DbException(error("boom", 404, False))
    assert str(exc) == "boom"
    assert exc.status_code == 404
    assert exc.trace is None
    exc = DbException(error("boom"))
    assert exc.status_code == 400
    assert exc.trace is None


@pytest.mark.parametrize("value, expected", [("false", False), ("0", False), ("true", True), ("On", True)])
def test_show_query_env_var(monkeypatch, value, expected):
    # "false" used to arrive as a non empty string, so it was truthy
    monkeypatch.setenv("DB_SHOW_QUERY", value)
    assert read_cnx_data({"type": "sqlite", "path": "x.db"})[2] is expected


def test_show_query_config_wins_over_env_var(monkeypatch):
    monkeypatch.setenv("DB_SHOW_QUERY", "not a bool")
    assert read_cnx_data({"type": "sqlite", "path": "x.db", "show_query": False})[2] is False


def test_show_query_env_var_unset(monkeypatch):
    monkeypatch.delenv("DB_SHOW_QUERY", raising=False)
    assert read_cnx_data({"type": "sqlite", "path": "x.db"})[2] is False


def test_uri(monkeypatch):
    monkeypatch.delenv("DB_URI", raising=False)
    uri = "postgresql+psycopg://user:pass@localhost:5433/test"
    assert read_cnx_data({"uri": uri})[0] == uri


def test_uri_wins_over_type():
    uri = "sqlite:///other.db"
    assert read_cnx_data({"uri": uri, "type": "sqlite", "path": "x.db"})[0] == uri


def test_uri_keeps_other_settings():
    modifiers = {"lower_table": True}
    cnx_data, cnx_data_extra, show_query, mods, config_log = read_cnx_data({
        "uri": "sqlite:///x.db",
        "show_query": True,
        "modifiers": modifiers,
        "cnx_data_extra": {"echo": False},
        "log": {"path": "logdb/x.log", "level_log": "DEBUG", "backup_count": 3},
    })
    assert cnx_data == "sqlite:///x.db"
    assert cnx_data_extra == {"echo": False}
    assert show_query is True
    assert mods == modifiers
    assert config_log == {"level_log": "DEBUG", "log_path": "logdb/x.log", "backup_count": 3}


def test_uri_env_var(monkeypatch):
    monkeypatch.setenv("DB_URI", "sqlite:///env.db")
    assert read_cnx_data({})[0] == "sqlite:///env.db"
    # A config with type ignores DB_URI
    assert read_cnx_data({"type": "sqlite", "path": "x.db"})[0] == "sqlite:///x.db"


@pytest.mark.parametrize("uri", ["", "   ", 5, "not a url"])
def test_uri_not_valid(uri):
    with pytest.raises(DbException) as exc:
        read_cnx_data({"uri": uri})
    assert exc.value.status_code == 400
    assert "Not valid uri" in str(exc.value)


def test_uri_connects(tmp_path):
    from alchemy_api import Conexion
    uri = f"sqlite:///{tmp_path / 'uri.db'}"
    cnx_data, cnx_data_extra, show_query, modifiers, config_log = read_cnx_data({"uri": uri})
    cnx = Conexion(cnx_data, cnx_data_extra=cnx_data_extra, show_query=show_query,
                   modifiers=modifiers, config_log=config_log)
    cnx.exec_sql("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    assert cnx.exec_sql("SELECT count(*) AS n FROM t", ret=True) == [{"n": 0}]


@pytest.mark.parametrize("type_, expected", [
    ("mariadb", "mariadb+pymysql://u:p@h:1/d?charset=utf8"),
    ("async_mariadb", "mariadb+aiomysql://u:p@h:1/d?charset=utf8"),
    ("mysql", "mysql+pymysql://u:p@h:1/d?charset=utf8mb4"),
    ("async_mysql", "mysql+aiomysql://u:p@h:1/d?charset=utf8mb4"),
])
def test_mysql_types(type_, expected):
    cfg = {"type": type_, "server": "h", "port": 1, "user": "u", "password": "p", "db": "d"}
    assert read_cnx_data(cfg)[0] == expected


def test_mssql_type():
    cfg = {"type": "mssql", "server": "h", "port": 1433, "user": "u", "password": "p", "db": "d"}
    assert read_cnx_data(cfg)[0] == "mssql+pymssql://u:p@h:1433/d?charset=utf8"
