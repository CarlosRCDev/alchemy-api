"""Role permissions for the REST apis (Flask and FastAPI)

Permissions come from the "permissions" section of the settings json, next to "database".
Each role has the operations ("roles") and the tables ("tables") it can use:

    "permissions": {
        "admin": {"roles": ["*"], "tables": ["*"]},
        "reader": {"roles": ["tables", "schema", "select"], "tables": ["users", "data"]}
    }

"*" allows every operation / every table. read_permissions gives two maps, one per control:
without any "roles" key there is no operation control, without any "tables" key no table control.
When a key is used by some role, the roles without it get nothing (fail closed).
The app gives the role of each request with a get_role(request) function.
"""
from .utils import DbException, error

# One operation per endpoint group
OPERATIONS = frozenset({
    "tables",      # GET  /db/tables
    "schema",      # POST /db/schema
    "select",      # POST /db/select
    "insert",      # POST /db/insert
    "update",      # POST /db/update
    "delete",      # POST /db/delete
    "sql",         # POST /db/sql
    "log_read",    # GET  /log, /log/order/..., /log/reverse/...
    "log_delete",  # DELETE /delete_log/...
})
ALL_OPERATIONS = "*"
ALL_TABLES = "*"
PERMISSION_KEYS = ("roles", "tables")
_WRITE_OPERATIONS = frozenset({"insert", "update", "delete", "sql"})


def read_permissions(cfg_permissions:dict | None) -> tuple[dict | None, dict | None]:
    """"permissions" section of the settings json -> (roles, tables), as read_roles and read_tables.
    Each is None when no role uses its key"""
    if not cfg_permissions:
        return None, None
    for role, permissions in cfg_permissions.items():
        if not isinstance(permissions, dict):
            raise ValueError(f"Permissions of role {role!r} must be an object with {list(PERMISSION_KEYS)}")
        unknown = set(permissions) - set(PERMISSION_KEYS)
        if unknown:
            raise ValueError(f"Role {role!r}: unknown keys {sorted(unknown)}, valid: {list(PERMISSION_KEYS)}")

    def section(key, reader):
        if not any(key in permissions for permissions in cfg_permissions.values()):
            return None
        # Roles without the key get an empty list: nothing allowed
        return reader({role: permissions.get(key, []) for role, permissions in cfg_permissions.items()})

    return section("roles", read_roles), section("tables", read_tables)


def read_roles(cfg_roles:dict | None) -> dict[str, frozenset] | None:
    """{role: operations} -> {role: allowed operations}. None if there are no roles"""
    if not cfg_roles:
        return None
    roles = {}
    for role, operations in cfg_roles.items():
        if isinstance(operations, str):
            operations = [operations]
        operations = set(operations)
        if ALL_OPERATIONS in operations:
            roles[role] = OPERATIONS
            continue
        unknown = operations - OPERATIONS
        if unknown:
            raise ValueError(
                f"Role {role!r}: unknown operations {sorted(unknown)}, valid: {sorted(OPERATIONS)} or {ALL_OPERATIONS!r}"
            )
        roles[role] = frozenset(operations)
    return roles


def read_tables(cfg_tables:dict | None) -> dict[str, frozenset | None] | None:
    """{role: tables} -> {role: allowed tables (casefolded), None = every table}.
    None if there is no table control"""
    if not cfg_tables:
        return None
    tables = {}
    for role, names in cfg_tables.items():
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, (list, tuple, set)) or not all(isinstance(name, str) and name for name in names):
            raise ValueError(f"Tables of role {role!r} must be a list of table names or {ALL_TABLES!r}")
        # None: every table. Names are compared case insensitive (Oracle returns them uppercase)
        tables[role] = None if ALL_TABLES in names else frozenset(name.casefold() for name in names)
    return tables


def _require_role(get_role, role:str | None, section:str):
    if get_role is None:
        # Section configured but no way to know the role: refuse instead of allowing everything
        raise DbException(error(f"{section} configured but get_role is not set in the app", 500, False)) from None
    if role is None:
        raise DbException(error("Role required", 401, False)) from None


def check_permission(roles:dict | None, get_role, role:str | None, operation:str):
    """Raises DbException if the role can not use the operation. roles=None: everything allowed"""
    if roles is None:
        return
    _require_role(get_role, role, "Roles")
    if operation not in roles.get(role, ()):
        raise DbException(error(f"Role {role!r} can not use {operation}", 403, False)) from None


def table_allowed(tables:dict | None, role:str | None, table:str | None) -> bool:
    """True if the role can use the table. table=None asks for every table (e.g. raw SQL).
    tables=None: everything allowed. Unknown role: nothing allowed"""
    if tables is None:
        return True
    if role not in tables:
        return False
    allowed = tables[role]
    if allowed is None:
        return True
    return table is not None and table.casefold() in allowed


def check_table(tables:dict | None, get_role, role:str | None, table:str | None):
    """Raises DbException if the role can not use the table. table=None needs access to every table"""
    if tables is None:
        return
    _require_role(get_role, role, "Tables")
    if not table_allowed(tables, role, table):
        target = f"table {table!r}" if table is not None else f"every table ({ALL_TABLES!r})"
        raise DbException(error(f"Role {role!r} can not use {target}", 403, False)) from None


def role_permissions(cnx, roles:dict | None, tables:dict | None, get_role, role:str | None,
                     allow_raw_sql:bool=False) -> dict:
    """What the role can really do: {"role": ..., "operations": [...], "tables": [...]}.

    operations leaves out what the connection refuses (read_only) and raw SQL when it is disabled or
    the role does not have every table. tables are the ones of the settings, ["*"] for every table.
    Without permissions configured everything is allowed. No role: 401, unknown role: 403"""
    for section in (roles, tables):
        if section is not None:
            _require_role(get_role, role, "Permissions")
            if role not in section:
                raise DbException(error(f"Role {role!r} does not exist", 403, False)) from None
    operations = set(OPERATIONS if roles is None else roles[role])
    if getattr(cnx, "_read_only", False):
        operations -= _WRITE_OPERATIONS
    if not allow_raw_sql or not table_allowed(tables, role, None):
        operations.discard("sql")
    allowed = None if tables is None else tables[role]
    if allowed is None:
        names = [ALL_TABLES]
    else:
        names = sorted(name.upper() if cnx._ret_upper_table else name for name in allowed)
    return {"role": role, "operations": sorted(operations), "tables": names}


def filter_tables(tables:dict | None, get_role, role:str | None, names:list) -> list:
    """Only the names the role can use (for /db/tables)"""
    if tables is None:
        return list(names)
    _require_role(get_role, role, "Tables")
    return [name for name in names if table_allowed(tables, role, name)]
