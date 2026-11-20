# Discovery Agent - developer commands (spec 10 §3.4).
# Backend runs from backend/ with uv; frontend from frontend/ with npm. No containers needed for development.
.PHONY: setup dev backend frontend test test-backend test-eval test-frontend lint lint-backend lint-frontend build chat eval \
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

test: test-backend test-eval test-frontend

test-backend:
	cd backend && uv run pytest -q

# Evaluation tests (spec 24 §7): no model, run with the backend's environment and pytest settings.
test-eval:
	cd backend && uv run pytest -q -p no:cacheprovider -c pyproject.toml ../eval/tests

test-frontend:
	@if [ -f frontend/package.json ]; then cd frontend && npm test; fi

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check . ../eval && uv run ruff format --check . ../eval && uv run pyright

lint-frontend:
	@if [ -f frontend/package.json ]; then cd frontend && npm run lint && npm run typecheck; fi

build:
	docker build -t discovery-agent:local .

chat:
	cd backend && DEPLOYMENT_STAGE=local uv run python scripts/chat.py $(ARGS)

# The evaluation (spec 24 §3.5): QUICK=1 (quick personas), FRESH=1 (no cache for app and expert calls),
# URL=https://... (against a running app), SEED=1 (seed finished sessions into Cosmos), ARGS for more.
eval:
	cd backend && PYTHONPATH=.. uv run python -m eval.run $(if $(QUICK),--quick) $(if $(FRESH),--fresh) \
		$(if $(URL),--url $(URL)) $(if $(SEED),--seed-cosmos) $(ARGS)

# Deployment checks (spec 25 §4). None of these creates or changes anything in Azure.
image-check:
	infra/scripts/check-image.sh

infra-lint:
	infra/scripts/lint-bicep.sh

infra-test:
	cd backend && uv run pytest -q -p no:cacheprovider ../infra/tests

smoke:
	infra/scripts/smoke.sh "$(URL)" $(VERSION)
