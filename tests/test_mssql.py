import pytest

from alchemy_api import Conexion


@pytest.fixture
def mssql_cnx(backend, db_cfg):
    if backend != "mssql":
        pytest.skip("SQL Server only")
    return Conexion(**db_cfg)


def test_limit_percent(mssql_cnx):
    # limit < 1 is a percentage: TOP (0.5) PERCENT, not truncated to TOP 0 PERCENT (no rows)
    assert len(mssql_cnx.select("users", limit=0.5)) == 1
    assert len(mssql_cnx.select("users", limit=0.5, filterby={"id": 99})) == 0
    assert len(mssql_cnx.select("users", limit=4)) == 4


def test_offset_without_orderby_uses_primary_key(mssql_cnx):
    rows = mssql_cnx.select("users", offset=1, limit=2)
    assert [row["id"] for row in rows] == [2, 3]
    # An explicit orderby is kept
    rows = mssql_cnx.select("users", orderby={"id": True}, offset=1, limit=2)
    assert [row["id"] for row in rows] == [3, 2]
