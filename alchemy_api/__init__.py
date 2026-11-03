from .conexion import Conexion
# from .api_db import api_db

__all__ = ["Conexion", "AsyncConexion"]


def __getattr__(name):
    # AsyncConexion needs greenlet (pip install "sqlalchemy-rest-api[async]"),
    # so it is only imported when used and Conexion works with the core install
    if name == "AsyncConexion":
        from .async_conexion import AsyncConexion
        return AsyncConexion
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
