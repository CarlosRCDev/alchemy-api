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
