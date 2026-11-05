# syntax=docker/dockerfile:1
# REST api image (FastAPI + uvicorn) with every database driver.
# Build from the repository root (the context must include pyproject.toml and alchemy_api/):
#   docker build -f deployments/Dockerfile -t sqlalchemy-rest-api .
# Only some drivers (extras of pyproject.toml, comma separated; fastapi is always added):
#   docker build -f deployments/Dockerfile --build-arg EXTRAS=postgres,async -t sqlalchemy-rest-api .
# Other app (any file of the context with a FastAPI "app") and the packages it needs, e.g. JWT authentication:
#   docker build -f deployments/Dockerfile --build-arg APP=example/api_fastapi_jwt.py \
#       --build-arg PACKAGES="pyjwt[crypto]>=2.10" -t sqlalchemy-rest-api:jwt .
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS build
ARG EXTRAS=async,oracle,mariadb,mysql,mssql,postgres
# Extra pip packages for the app (space separated), not in uv.lock
ARG PACKAGES=""
COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY alchemy_api ./alchemy_api
# Dependencies pinned by uv.lock (with hashes), then the library built as a wheel.
# EXTRAS "a,b" -> --extra fastapi --extra a --extra b (uv fails on an unknown extra)
RUN extra_args="--extra fastapi" \
    && for extra in $(echo "$EXTRAS" | tr ',' ' '); do extra_args="$extra_args --extra $extra"; done \
    && echo "uv extras: $extra_args" \
    && uv export --frozen --no-dev --no-emit-project $extra_args -o /tmp/requirements.txt \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --require-hashes -r /tmp/requirements.txt \
    && uv build --wheel --out-dir /tmp/dist \
    && uv pip install --python /opt/venv/bin/python --no-deps /tmp/dist/*.whl \
    && if [ -n "$PACKAGES" ]; then uv pip install --python /opt/venv/bin/python $PACKAGES; fi

FROM python:${PYTHON_VERSION}-slim
# The app served by uvicorn, copied as /app/app.py
ARG APP=deployments/app.py
LABEL org.opencontainers.image.title="sqlalchemy-rest-api" \
      org.opencontainers.image.description="REST api over existing databases with SQLAlchemy reflection" \
      org.opencontainers.image.source="https://github.com/CarlosRCDev/alchemy-api" \
      org.opencontainers.image.licenses="MIT"
RUN useradd --create-home --uid 10001 app
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CONFIG_FILE=/app/config/config.json
WORKDIR /app
COPY ${APP} ./app.py
# db/ (sqlite) and logdb/ (logs) are writable by the app user, mount volumes there
RUN mkdir -p config db logdb && chown app:app db logdb
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
