import asyncio

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from alchemy_api import AsyncConexion
from alchemy_api.utils import DbExecption


def run(coro):
    return asyncio.run(coro)


async def _cnx(cfg, **kwargs):
    return await AsyncConexion.create(**cfg, **kwargs)


def test_async_select(async_db_cfg):
    async def main():
        cnx = await _cnx(async_db_cfg)
        return await cnx.select("users", filterby={"age": 30}, orderby={"id": False})
    assert [r["name"] for r in run(main())] == ["ana", "marta"]


def test_async_with_engine_only(async_db_cfg):
    # Previously failed with AttributeError due to name mangling
    async def main():
        engine = create_async_engine(async_db_cfg["cnx_data"])
        cnx = await AsyncConexion.create(None, engine=engine)
        rows = await cnx.select("users", count=True)
        await engine.dispose()
        return rows
    assert list(run(main()).values()) == [4]


def test_async_error_is_dbexception(async_db_cfg):
    # Previously the real error was hidden by an AttributeError on self.__logger
    async def main():
        cnx = await _cnx(async_db_cfg)
        await cnx.exec_sql("SELECT * FROM missing_table", ret=True)
    with pytest.raises(DbExecption):
        run(main())


def test_async_insert_update_delete(async_db_cfg):
    async def main():
        cnx = await _cnx(async_db_cfg)
        await cnx.insert("users", {"id": 50, "name": "async", "age": 5})
        updated = await cnx.update("users", {"age": 6}, filterby={"id": 50})
        deleted = await cnx.delete("users", filterby={"id": 50})
        return updated.rowcount, deleted.rowcount, await cnx.select("users", count=True)
    updated, deleted, count = run(main())
    assert (updated, deleted, list(count.values())) == (1, 1, [4])


def test_async_update_delete_require_filter(async_db_cfg):
    async def main():
        cnx = await _cnx(async_db_cfg, _raise=False)
        with pytest.raises(DbExecption):
            await cnx.update("users", {"age": 0})
        with pytest.raises(DbExecption):
            await cnx.delete("users", filterby={"typo": 1})
        return await cnx.select("users", count=True)
    assert list(run(main()).values()) == [4]
