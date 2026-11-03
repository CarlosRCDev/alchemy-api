from importlib.metadata import PackageNotFoundError, version

from .conexion import Conexion
# from .api_db import api_db

__all__ = ["Conexion", "AsyncConexion", "__version__"]

try:
    # Installed package metadata (pyproject.toml is not shipped in the wheel)
    __version__ = version("sqlalchemy-rest-api")
except PackageNotFoundError:
    # Source used without installing it (e.g. only with PYTHONPATH)
    __version__ = "0.0.0"


def __getattr__(name):
    # AsyncConexion needs greenlet (pip install "sqlalchemy-rest-api[async]"),
    # so it is only imported when used and Conexion works with the core install
    if name == "AsyncConexion":
        from .async_conexion import AsyncConexion
        return AsyncConexion
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
