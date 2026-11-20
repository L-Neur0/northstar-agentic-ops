# Dockerfile: the one image of the Discovery Agent (spec 25 §3.2, D4, D6).
#
# Why it exists: the same image runs locally (`docker run`, `make image-check`)
#   and on Azure Container Apps. FastAPI serves the API and the built React app
#   from frontend/dist with a page fallback (spec 10 §3.8).
# What it does: three stages. `web` builds the frontend with Node; `deps`
#   installs the locked backend dependencies with uv; `runtime` copies only the
#   virtualenv, backend/app, config/ and frontend/dist into a slim Python image
#   that mirrors the repo layout, so the default paths of spec 10 work as is.
# Rules: runs as uid/gid 10001; one uvicorn worker (D6); APP_VERSION is a build
#   argument so /api/health reports the image actually running.
# Must not: contain uv, Node, compilers, tests, .work/ or brief/; set
#   DEPLOYMENT_STAGE (stage is never guessed: Azure sets demo explicitly) or any
#   secret; declare a HEALTHCHECK (Container Apps uses the Bicep probes).
# Acceptance criteria: AC-25.1 to AC-25.5, AC-25.7.

# ---- web: build the single-page app --------------------------------------------
FROM node:22.21-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- deps: locked Python dependencies into /app/backend/.venv -------------------
FROM python:3.12.16-slim-bookworm AS deps
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- runtime: slim, non-root ---------------------------------------------------
FROM python:3.12.16-slim-bookworm AS runtime
ARG APP_VERSION=0.0.0-local
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --no-log-init --shell /usr/sbin/nologin app
COPY --from=deps /app/backend/.venv /app/backend/.venv
COPY backend/app /app/backend/app
COPY config /app/config
COPY --from=web /src/frontend/dist /app/frontend/dist
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    APP_VERSION=${APP_VERSION:-0.0.0-local}
WORKDIR /app/backend
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-graceful-shutdown", "20"]
