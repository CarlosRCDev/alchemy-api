import json

import pytest

from alchemy_api import Conexion
from alchemy_api.utils import read_cnx_data
from conftest import ORACLE_CONFIG, ROOT


@pytest.fixture
def oracle_cnx(backend, db_url):
    if backend != "oracle":
        pytest.skip("Oracle only")
    # Built from the settings file, like the library is used in real apps
    with open(ROOT / ORACLE_CONFIG) as f:
        cnx_data, cnx_data_extra, show_query, modifiers, _ = read_cnx_data(json.load(f)["database"])
    return Conexion(cnx_data, cnx_data_extra=cnx_data_extra, show_query=show_query, modifiers=modifiers)


def test_modifiers_upper_case(oracle_cnx):
    tables, _ = oracle_cnx.tables()
    assert tables == ["USERS"]
    rows = oracle_cnx.select("USERS", colset=["NAME", "AGE"], filterby={"ID": 1})
    assert rows == [{"NAME": "ana", "AGE": 30}]


def test_limit_percent(oracle_cnx):
    # limit < 1 is sent as FETCH FIRST <limit> PERCENT ROWS ONLY (0.5 -> 0.5 %, not 50 %)
    assert len(oracle_cnx.select("users", limit=0.5)) <= 4
    assert len(oracle_cnx.select("users", limit=4)) == 4
