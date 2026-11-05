"""REST api with FastAPI and JWT authentication, users and permissions in their own database

Self contained (no demo_data): it can replace deployments/app.py. The library is used twice:
  - data database ("database" in the settings): the only one served by /db/...
  - users database ("users_database" in the settings, default sqlite db/db_users.db): roles, users with
    their password hashes, and the operations and tables of each role. Never exposed by the api,
    opened read only while serving.
The settings file only has the databases: a "permissions" section is refused (roles live in the users database).
The library itself is not changed: the role of each request is given to it with app.state.get_role.

Users database (created with the init-users-db command):
    api_roles            role, description
    api_users            username, password_hash, role (-> api_roles), active
    api_role_operations  role (-> api_roles), operation    ("*" = every operation)
    api_role_tables      role (-> api_roles), table_name   ("*" = every table)
A role without operation/table rows gets nothing, a role not in api_roles does not exist (fail closed).
Roles and permissions are reloaded every PERMISSIONS_TTL seconds; with local login the role and "active"
of the user are read on every request, so disabling a user or changing its role works at once,
also with tokens already issued.

Commands (run from the folder of the settings, CONFIG_FILE as for the api):
    python api_fastapi_jwt.py init-users-db               # tables + default roles admin/editor/reader
    python api_fastapi_jwt.py add-role <role> [description]
    python api_fastapi_jwt.py delete-role <role>          # only without users; removes its permissions
    python api_fastapi_jwt.py add-user <user> <role>      # asks the password; updates it if the user exists
    python api_fastapi_jwt.py disable-user <user>
    python api_fastapi_jwt.py grant <role> operation|table <value>
    python api_fastapi_jwt.py revoke <role> operation|table <value>
    python api_fastapi_jwt.py show                        # roles, permissions and users
    python api_fastapi_jwt.py                             # runs the api (uvicorn)

Environment variables:
  Databases:
    CONFIG_FILE        settings json with "database" and optional "users_database" (default: config_jwt.json next to this file).
                       Without "database": DB_URI or DB_TYPE/DB_SERVER/... as deployments/app.py
    USERS_DB_PATH      sqlite file of the users database when there is no "users_database" (default db/db_users.db)
    PERMISSIONS_TTL    seconds between permission reloads (default 30)
    DB_ALLOW_RAW_SQL   enables POST /db/sql (default false). READ_ONLY is read by Conexion.
  Token validation, exactly one key source (the api does not start without one):
    JWT_SECRET         shared secret (HS256, >= 32 chars): local login with POST /auth/token against api_users
    JWT_JWKS_URL       identity provider keys (Keycloak, Auth0, Azure AD...): role from the token claim,
                       permissions of that role from the users database
    JWT_PUBLIC_KEY     PEM public key (or JWT_PUBLIC_KEY_FILE), same as JWKS
    JWT_ALGORITHMS     accepted algorithms (default HS256 with a secret, RS256 otherwise)
    JWT_ISSUER, JWT_AUDIENCE   required "iss" / "aud" (recommended)
    JWT_ROLE_CLAIM     claim with the role for provider tokens, dotted path (default "role"); a list
                       (e.g. Keycloak "realm_access.roles") gives its first role with permissions
    JWT_LEEWAY         clock skew tolerance in seconds (default 30)
    JWT_MINUTES        lifetime of local tokens (default 30)

Run locally from the project root:
    uv run python example/api_fastapi_jwt.py init-users-db
    uv run python example/api_fastapi_jwt.py add-user marta reader
    JWT_SECRET="$(openssl rand -hex 32)" JWT_ISSUER=local uv run python example/api_fastapi_jwt.py
    TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/token -H "Content-Type: application/json" \\
            -d '{"username": "marta", "password": "..."}' | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
    curl http://127.0.0.1:8000/db/tables -H "Authorization: Bearer $TOKEN"
Needs the [jwt] extra: pip install "sqlalchemy-rest-api[fastapi,jwt]" (PyJWT with crypto for RS256).
Docker image with this app instead of deployments/app.py: see deployments/Dockerfile (APP, EXTRAS=...,jwt).
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
from hmac import compare_digest
import json
import logging
from os import getenv
from pathlib import Path
import secrets
import sys
from threading import Lock
import time

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from alchemy_api import Conexion, __version__
from alchemy_api.api_fastapi import api_db, api_log, api_log_delete, register_exception_handlers
from alchemy_api.permissions import ALL_OPERATIONS, OPERATIONS, read_permissions
from alchemy_api.utils import DbException, env_bool, error, read_cnx_data

logger = logging.getLogger("uvicorn.error")

CONFIG_FILE = Path(getenv("CONFIG_FILE", Path(__file__).resolve().parent / "config_jwt.json"))
HASH_ITERATIONS = 600_000

ROLES_TABLE = "api_roles"
USERS_TABLE = "api_users"
OPERATIONS_TABLE = "api_role_operations"
TABLES_TABLE = "api_role_tables"
# Created by init-users-db; plain types so the same DDL works in every backend
# In creation order (api_roles first: the others reference it)
USERS_DDL = {
    ROLES_TABLE: "CREATE TABLE api_roles (role VARCHAR(100) PRIMARY KEY, description VARCHAR(255))",
    USERS_TABLE: "CREATE TABLE api_users (username VARCHAR(100) PRIMARY KEY, password_hash VARCHAR(255) NOT NULL, "
                 "role VARCHAR(100) NOT NULL REFERENCES api_roles (role), active INTEGER DEFAULT 1 NOT NULL)",
    OPERATIONS_TABLE: "CREATE TABLE api_role_operations (role VARCHAR(100) NOT NULL REFERENCES api_roles (role), "
                      "operation VARCHAR(50) NOT NULL, PRIMARY KEY (role, operation))",
    TABLES_TABLE: "CREATE TABLE api_role_tables (role VARCHAR(100) NOT NULL REFERENCES api_roles (role), "
                  "table_name VARCHAR(255) NOT NULL, PRIMARY KEY (role, table_name))",
}
DEFAULT_ROLES = {
    "admin": {"description": "everything", "operations": ["*"], "tables": ["*"]},
    "editor": {"description": "read and write its tables",
               "operations": ["tables", "schema", "select", "insert", "update", "delete", "log_read"], "tables": []},
    "reader": {"description": "read its tables", "operations": ["tables", "schema", "select"], "tables": []},
}


# --- Settings and connections ---------------------------------------------
def load_settings() -> dict:
    if not CONFIG_FILE.is_file():
        logger.info("No settings file %s, data connection from environment variables", CONFIG_FILE)
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def _conexion(cfg:dict, **kwargs) -> Conexion:
    cnx_data, cnx_data_extra, show_query, modifiers, config_log = read_cnx_data(dict(cfg))
    return Conexion(cnx_data, cnx_data_extra=cnx_data_extra, show_query=show_query,
                    modifiers=modifiers, config_log=config_log, **kwargs)


def users_db_config(settings:dict) -> dict:
    if "users_database" in settings:
        return settings["users_database"]
    path = Path(getenv("USERS_DB_PATH", "db/db_users.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return {"type": "sqlite", "path": str(path)}


def open_users_db(settings:dict, read_only:bool) -> Conexion:
    # read_only given explicitly: the READ_ONLY env var is meant for the data database
    return _conexion(users_db_config(settings), read_only=read_only)


def _has_tables(users_cnx:Conexion) -> bool:
    tables, _ = users_cnx.tables()
    return set(USERS_DDL) <= {table.lower() for table in tables}


# --- Passwords --------------------------------------------------------------
def hash_password(password:str, iterations:int=HASH_ITERATIONS) -> str:
    """"pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>" """
    salt = secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password:str, stored:str) -> bool:
    try:
        method, iterations, salt, digest = stored.split("$")
        if method != "pbkdf2_sha256":
            return False
        computed = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return compare_digest(computed, bytes.fromhex(digest))


# A valid hash to compare against when the user does not exist: same time for unknown user and wrong password
_DUMMY_HASH = hash_password(secrets.token_hex(16))


# --- Users database (through the library) -----------------------------------
class UsersStore:
    """Users and role permissions read with a Conexion of the users database"""

    def __init__(self, cnx:Conexion, ttl:int):
        self.cnx = cnx
        self.ttl = ttl
        self._lock = Lock()
        self._loaded_at = 0.0
        self.roles = {}
        self.tables = {}

    def get_user(self, username:str) -> dict | None:
        rows = self.cnx.select(USERS_TABLE, filterby={"username": username})
        return rows[0] if rows else None

    def read_permissions(self) -> tuple[dict, dict]:
        """{role: operations}, {role: tables} of the roles in api_roles.
        Every role has both keys, so a role without rows gets nothing (fail closed)"""
        cfg = {row["role"]: {"roles": [], "tables": []} for row in self.cnx.select(ROLES_TABLE)}
        for table, column, key in ((OPERATIONS_TABLE, "operation", "roles"), (TABLES_TABLE, "table_name", "tables")):
            for row in self.cnx.select(table):
                if row["role"] in cfg:
                    cfg[row["role"]][key].append(row[column])
                else:
                    logger.warning("%s: role %r not in %s, ignored", table, row["role"], ROLES_TABLE)
        roles, tables = read_permissions(cfg)
        # No roles at all: nothing allowed, never "no control"
        return roles or {}, tables or {}

    def refresh(self, app_state, force:bool=False):
        """Reloads the permissions into app.state when the TTL expired; keeps the old ones on error"""
        if not force and time.monotonic() - self._loaded_at < self.ttl:
            return
        with self._lock:
            if not force and time.monotonic() - self._loaded_at < self.ttl:
                return
            try:
                self.roles, self.tables = self.read_permissions()
            except (DbException, ValueError) as e:
                if force:
                    raise
                logger.error("Permissions not reloaded, keeping the previous ones: %s", e)
            self._loaded_at = time.monotonic()
            app_state.roles, app_state.tables = self.roles, self.tables


# --- JWT validation ---------------------------------------------------------
class TokenValidator:
    """Validates tokens with the key source of the environment variables"""

    def __init__(self):
        jwks_url = getenv("JWT_JWKS_URL")
        public_key = getenv("JWT_PUBLIC_KEY")
        if not public_key and getenv("JWT_PUBLIC_KEY_FILE"):
            public_key = Path(getenv("JWT_PUBLIC_KEY_FILE")).read_text()
        self.secret = getenv("JWT_SECRET")
        sources = [name for name, value in (("JWT_JWKS_URL", jwks_url), ("JWT_PUBLIC_KEY", public_key), ("JWT_SECRET", self.secret)) if value]
        if len(sources) != 1:
            # Fail closed: without exactly one key source no token could be checked safely
            raise RuntimeError(f"Set exactly one of JWT_JWKS_URL, JWT_PUBLIC_KEY(_FILE) or JWT_SECRET (got {sources or 'none'})")
        if self.secret and len(self.secret) < 32:
            raise RuntimeError("JWT_SECRET must have at least 32 characters, e.g. openssl rand -hex 32")

        default_algorithms = "HS256" if self.secret else "RS256"
        self.algorithms = [a.strip() for a in getenv("JWT_ALGORITHMS", default_algorithms).split(",") if a.strip()]
        if "none" in (a.lower() for a in self.algorithms):
            raise RuntimeError("JWT_ALGORITHMS can not include none")
        if bool(self.secret) != all(a.startswith("HS") for a in self.algorithms):
            # A public key used as HMAC secret would let anyone sign tokens (algorithm confusion)
            raise RuntimeError("JWT_SECRET only with HS* algorithms, public keys/JWKS only with asymmetric ones")

        self.jwks = jwt.PyJWKClient(jwks_url, cache_keys=True) if jwks_url else None
        self.key = public_key or self.secret
        self.issuer = getenv("JWT_ISSUER") or None
        self.audience = getenv("JWT_AUDIENCE") or None
        self.role_claim = getenv("JWT_ROLE_CLAIM", "role")
        self.leeway = int(getenv("JWT_LEEWAY", "30"))
        if not self.issuer:
            logger.warning("JWT_ISSUER not set: tokens of any issuer signed with the key are accepted")

    @property
    def local(self) -> bool:
        """Tokens issued by this api (POST /auth/token) instead of an identity provider"""
        return bool(self.secret)

    def claims(self, token:str) -> dict:
        key = self.jwks.get_signing_key_from_jwt(token).key if self.jwks else self.key
        return jwt.decode(
            token,
            key,
            algorithms=self.algorithms,  # fixed list: the "alg" of the token is never trusted
            issuer=self.issuer,
            audience=self.audience,
            leeway=self.leeway,
            options={"require": ["exp", "sub"], "verify_aud": self.audience is not None},
        )

    def claim_role(self, claims:dict, known_roles) -> str | None:
        value = claims
        for part in self.role_claim.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            # e.g. Keycloak realm_access.roles: the first one with permissions
            return next((role for role in value if role in known_roles), None)
        return None

    def issue(self, username:str, minutes:int) -> str:
        # Only "sub": the role is read from the users database on every request
        now = datetime.now(timezone.utc)
        claims = {"sub": username, "iat": now, "exp": now + timedelta(minutes=minutes)}
        if self.issuer:
            claims["iss"] = self.issuer
        if self.audience:
            claims["aud"] = self.audience
        return jwt.encode(claims, self.secret, algorithm=self.algorithms[0])


def make_get_role(validator:TokenValidator, store:UsersStore, app_state):
    def get_role(request) -> str | None:
        """Role of "Authorization: Bearer <jwt>", None if missing or not valid. Cached per request"""
        if hasattr(request.state, "jwt_role"):
            return request.state.jwt_role
        store.refresh(app_state)
        role = None
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and token:
            try:
                claims = validator.claims(token)
                if validator.local:
                    user = store.get_user(claims["sub"])
                    # Disabled users and roles not in api_roles get nothing
                    role = user["role"] if user and user["active"] and user["role"] in store.roles else None
                else:
                    role = validator.claim_role(claims, store.roles.keys())
            except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
                # Expired, bad signature, wrong issuer/audience, unknown key...
                logger.info("Token refused: %s", e)
        request.state.jwt_role = role
        return role
    return get_role


# --- App --------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):
    validator = TokenValidator()
    settings = load_settings()
    if "permissions" in settings:
        # Avoids believing that a leftover section still applies
        raise RuntimeError(f"{CONFIG_FILE}: remove \"permissions\", roles and permissions are in the users database")
    app.state.cnx = _conexion(settings.get("database", {}))
    users_cnx = open_users_db(settings, read_only=True)
    if users_cnx._engine.url == app.state.cnx._engine.url:
        # The /db endpoints would expose the password hashes
        raise RuntimeError("The users database must not be the data database")
    if not _has_tables(users_cnx):
        raise RuntimeError(f"Users database without tables {sorted(USERS_DDL)}: run the init-users-db command")
    app.state.users_cnx = users_cnx
    app.state.allow_raw_sql = env_bool("DB_ALLOW_RAW_SQL")
    store = UsersStore(users_cnx, int(getenv("PERMISSIONS_TTL", "30")))
    store.refresh(app.state, force=True)
    # The only link with the library: how to know the role of a request
    app.state.get_role = make_get_role(validator, store, app.state)
    app.state.validator = validator
    app.state.store = store
    yield
    app.state.cnx._engine.dispose()
    users_cnx._engine.dispose()


def require_token(request: Request):
    """Every api request needs a valid token. Sync: FastAPI runs it in a thread (database/JWKS calls)"""
    if request.app.state.get_role(request) is None:
        raise DbException(error("Valid Bearer token required", 401, False)) from None


# Declares "Authorization: Bearer" in OpenAPI for the "Authorize" button in /docs
bearer = HTTPBearer(auto_error=False, description="JWT access token")
protected = [Depends(bearer), Depends(require_token)]

app = FastAPI(
    title="sqlalchemy-rest-api (JWT)",
    version=__version__,
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
)
register_exception_handlers(app)
app.include_router(api_db, prefix="/db", dependencies=protected)
app.include_router(api_log, prefix="/log", dependencies=protected)
app.include_router(api_log_delete, prefix="/delete_log", dependencies=protected)


class Login(BaseModel):
    username: str
    password: str


@app.post("/auth/token", tags=["auth"])
def login(body: Login, request: Request):
    # Sync on purpose: FastAPI runs it in a thread, the slow password hash does not block the event loop
    validator = request.app.state.validator
    if not validator.local:
        raise HTTPException(status_code=404, detail="Local login disabled: tokens come from the identity provider")
    user = request.app.state.store.get_user(body.username)
    # The hash is always computed: same time for unknown user and wrong password
    valid = verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH)
    if not user or not valid or not user["active"]:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    minutes = int(getenv("JWT_MINUTES", "30"))
    return {"access_token": validator.issue(body.username, minutes), "token_type": "bearer", "expires_in": minutes * 60}


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "version": __version__}


# --- Commands to manage the users database -----------------------------------
def init_users_db(cnx:Conexion):
    tables = {table.lower() for table in cnx.tables()[0]}
    for name, ddl in USERS_DDL.items():
        if name not in tables:
            cnx.exec_sql(ddl)
            print(f"Created {name}")
    # The library reflects the tables when it connects: reload them after creating
    cnx.post_conexion()
    # Default roles only in a new database, never over existing roles
    if not cnx.select(ROLES_TABLE):
        for role, perms in DEFAULT_ROLES.items():
            cnx.insert(ROLES_TABLE, {"role": role, "description": perms["description"]})
            if perms["operations"]:
                cnx.insert(OPERATIONS_TABLE, [{"role": role, "operation": op} for op in perms["operations"]])
            if perms["tables"]:
                cnx.insert(TABLES_TABLE, [{"role": role, "table_name": t} for t in perms["tables"]])
        print(f"Default roles {sorted(DEFAULT_ROLES)}; give tables to editor/reader with: grant <role> table <name>")


def _require_role(cnx:Conexion, role:str):
    if not cnx.select(ROLES_TABLE, filterby={"role": role}):
        sys.exit(f"Role {role!r} does not exist: add-role {role}")


def add_role(cnx:Conexion, role:str, description:str=""):
    if cnx.select(ROLES_TABLE, filterby={"role": role}):
        cnx.update(ROLES_TABLE, {"description": description}, filterby={"role": role})
        print(f"Updated role {role}")
    else:
        cnx.insert(ROLES_TABLE, {"role": role, "description": description})
        print(f"Created role {role}: grant {role} operation|table <value>")


def delete_role(cnx:Conexion, role:str):
    _require_role(cnx, role)
    users = [user["username"] for user in cnx.select(USERS_TABLE, filterby={"role": role})]
    if users:
        sys.exit(f"Role {role!r} has users {users}: change their role first")
    # Permissions first: they reference the role
    for table in (OPERATIONS_TABLE, TABLES_TABLE):
        if cnx.select(table, filterby={"role": role}):
            cnx.delete(table, filterby={"role": role})
    cnx.delete(ROLES_TABLE, filterby={"role": role})
    print(f"Deleted role {role}")


def add_user(cnx:Conexion, username:str, role:str):
    from getpass import getpass
    _require_role(cnx, role)
    password = getpass(f"Password for {username}: ")
    if len(password) < 4:
        sys.exit("Password must have at least 4 characters")
    if password != getpass("Repeat: "):
        sys.exit("Passwords do not match")
    data = {"password_hash": hash_password(password), "role": role, "active": 1}
    if cnx.select(USERS_TABLE, filterby={"username": username}):
        cnx.update(USERS_TABLE, data, filterby={"username": username})
        print(f"Updated {username} ({role})")
    else:
        cnx.insert(USERS_TABLE, {"username": username, **data})
        print(f"Created {username} ({role})")
    if not cnx.select(OPERATIONS_TABLE, filterby={"role": role}):
        print(f"Warning: role {role!r} has no operations yet: grant {role} operation <name>")


def change_permission(cnx:Conexion, grant:bool, role:str, kind:str, value:str):
    _require_role(cnx, role)
    if kind == "operation":
        table, column = OPERATIONS_TABLE, "operation"
        if value != ALL_OPERATIONS and value not in OPERATIONS:
            sys.exit(f"Unknown operation {value!r}, valid: {sorted(OPERATIONS)} or {ALL_OPERATIONS!r}")
    elif kind == "table":
        table, column = TABLES_TABLE, "table_name"
    else:
        sys.exit("Kind must be operation or table")
    row = {"role": role, column: value}
    exists = bool(cnx.select(table, filterby=row))
    if grant and not exists:
        cnx.insert(table, row)
    elif not grant and exists:
        cnx.delete(table, filterby=row)
    print(f"{'Granted' if grant else 'Revoked'}: {role} {kind} {value}")


def show(cnx:Conexion):
    print("Users:")
    for user in cnx.select(USERS_TABLE, colset=["username", "role", "active"], orderby={"username": False}):
        print(f"  {user['username']:<20} {user['role']:<15} {'active' if user['active'] else 'disabled'}")
    roles, tables = UsersStore(cnx, 0).read_permissions()
    print("Roles:")
    for row in cnx.select(ROLES_TABLE, orderby={"role": False}):
        role = row["role"]
        allowed = tables.get(role, frozenset())
        print(f"  {role:<15} {row['description'] or '':<28} operations: {sorted(roles.get(role, ()))}  "
              f"tables: {'*' if allowed is None else sorted(allowed)}")


def main(args:list):
    if not args:
        import uvicorn
        uvicorn.run(app)
        return
    command, rest = args[0], args[1:]
    # command -> (min, max) arguments
    usage = {"init-users-db": (0, 0), "add-role": (1, 2), "delete-role": (1, 1), "add-user": (2, 2),
             "disable-user": (1, 1), "grant": (3, 3), "revoke": (3, 3), "show": (0, 0)}
    if command not in usage or not usage[command][0] <= len(rest) <= usage[command][1]:
        sys.exit(__doc__)
    cnx = open_users_db(load_settings(), read_only=False)
    if command == "init-users-db":
        init_users_db(cnx)
        return
    if not _has_tables(cnx):
        sys.exit("Users database without tables: run init-users-db first")
    if command == "add-role":
        add_role(cnx, *rest)
    elif command == "delete-role":
        delete_role(cnx, *rest)
    elif command == "add-user":
        add_user(cnx, *rest)
    elif command == "disable-user":
        updated = cnx.update(USERS_TABLE, {"active": 0}, filterby={"username": rest[0]})
        print(f"Disabled {rest[0]}" if updated else f"No user {rest[0]}")
    elif command in ("grant", "revoke"):
        change_permission(cnx, command == "grant", *rest)
    elif command == "show":
        show(cnx)


if __name__ == "__main__":
    main(sys.argv[1:])
