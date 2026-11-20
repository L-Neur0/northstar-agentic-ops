# Discovery Agent - developer commands (spec 10 §3.4).
# Backend runs from backend/ with uv; frontend from frontend/ with npm. No containers needed for development.
.PHONY: setup dev backend frontend test test-backend test-frontend lint lint-backend lint-frontend build chat eval \
	image-check infra-lint infra-test smoke

setup:
	cd backend && uv sync
	@if [ -f frontend/package.json ]; then cd frontend && npm ci; fi

dev:
	$(MAKE) -j2 backend frontend

backend:
	cd backend && DEPLOYMENT_STAGE=local uv run uvicorn app.main:app --factory --reload --port 8000

frontend:
	@if [ -f frontend/package.json ]; then cd frontend && npm run dev; fi

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest -q

test-frontend:
	@if [ -f frontend/package.json ]; then cd frontend && npm test; fi

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright

lint-frontend:
	@if [ -f frontend/package.json ]; then cd frontend && npm run lint && npm run typecheck; fi

build:
	docker build -t discovery-agent:local .

chat:
	cd backend && DEPLOYMENT_STAGE=local uv run python scripts/chat.py $(ARGS)

eval:
	@echo "make eval is added in spec 40 (evaluation set)"

# Deployment checks (spec 25 §4). None of these creates or changes anything in Azure.
image-check:
	infra/scripts/check-image.sh

infra-lint:
	infra/scripts/lint-bicep.sh

infra-test:
	cd backend && uv run pytest -q -p no:cacheprovider ../infra/tests

smoke:
	infra/scripts/smoke.sh "$(URL)" $(VERSION)
