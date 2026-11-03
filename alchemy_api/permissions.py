"""Role permissions for the REST apis (Flask and FastAPI)

Roles come from the "roles" section of the settings json, next to "database":

    "roles": {
        "admin": ["*"],
        "reader": ["tables", "schema", "select"]
    }

"*" allows every operation. Without "roles" there is no permission control.
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


def read_roles(cfg_roles:dict | None) -> dict[str, frozenset] | None:
    """"roles" section of the settings json -> {role: allowed operations}. None if there are no roles"""
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


def check_permission(roles:dict | None, get_role, role:str | None, operation:str):
    """Raises DbException if the role can not use the operation. roles=None: everything allowed"""
    if roles is None:
        return
    if get_role is None:
        # Roles configured but no way to know the role: refuse instead of allowing everything
        raise DbException(error("Roles configured but get_role is not set in the app", 500, False)) from None
    if role is None:
        raise DbException(error("Role required", 401, False)) from None
    if operation not in roles.get(role, ()):
        raise DbException(error(f"Role {role!r} can not use {operation}", 403, False)) from None
