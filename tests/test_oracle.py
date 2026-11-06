import pytest

from alchemy_api import Conexion


@pytest.fixture
def oracle_cnx(backend, db_cfg):
    if backend != "oracle":
        pytest.skip("Oracle only")
    # Full config from the settings file, like the library is used in real apps
    return Conexion(**db_cfg)


def test_modifiers_upper_case(oracle_cnx):
    tables, _ = oracle_cnx.tables()
    assert tables == ["USERS"]
    rows = oracle_cnx.select("USERS", colset=["NAME", "AGE"], filterby={"ID": 1})
    assert rows == [{"NAME": "ana", "AGE": 30}]


def test_schema_upper_case(oracle_cnx):
    names = [col["name"] for col in oracle_cnx.schema("USERS")["columns"]]
    assert set(names) == {"ID", "NAME", "AGE", "CREATED"}


def test_limit_percent(oracle_cnx):
    # limit < 1 is sent as FETCH FIRST <limit> PERCENT ROWS ONLY (0.5 -> 0.5 %, not 50 %)
    assert len(oracle_cnx.select("users", limit=0.5)) <= 4
    assert len(oracle_cnx.select("users", limit=4)) == 4
