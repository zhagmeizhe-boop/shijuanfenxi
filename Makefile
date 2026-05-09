.PHONY: help install dev test lint lint-fix docker-up docker-down docker-logs docker-build docker-restart migrate migrate-create migrate-down db-reset clean api-docs shell psql redis-cli

help:
	@echo "Math Analysis System - available commands:"
	@echo ""
	@echo "  Development:"
	@echo "    make install          - install frontend dependencies"
	@echo "    make dev              - show the recommended local dev commands"
	@echo "    make test             - run backend tests"
	@echo "    make lint             - run backend lint checks"
	@echo "    make lint-fix         - auto-fix backend lint issues"
	@echo ""
	@echo "  Docker:"
	@echo "    make docker-up        - start all Docker services"
	@echo "    make docker-down      - stop all Docker services"
	@echo "    make docker-logs      - tail Docker logs"
	@echo "    make docker-build     - rebuild Docker images"
	@echo "    make docker-restart   - restart Docker services"
	@echo ""
	@echo "  Database:"
	@echo "    make migrate          - run Alembic migrations"
	@echo "    make migrate-create   - create a new Alembic revision"
	@echo "    make migrate-down     - roll back one Alembic revision"
	@echo "    make db-reset         - reset Docker database volumes"
	@echo ""
	@echo "  Utilities:"
	@echo "    make clean            - remove temporary files"
	@echo "    make api-docs         - generate openapi.json"
	@echo "    make shell            - open an API container shell"
	@echo "    make psql             - open PostgreSQL shell"
	@echo "    make redis-cli        - open Redis CLI"

install:
	@echo "Installing frontend dependencies with npm..."
	cd apps/web && npm install
	@echo "Backend local development uses the existing apps/api/venv environment."

dev:
	@echo "Start local development with 2 terminals:"
	@echo "  Terminal 1: cd apps/api && .\\venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8100"
	@echo "  Terminal 2: cd apps/web && npm run dev"
	@echo "  Frontend: http://localhost:3100"
	@echo "  Backend:  http://localhost:8100"

test:
	@echo "Running backend tests..."
	cd apps/api && poetry run pytest -v

lint:
	@echo "Running backend lint checks..."
	cd apps/api && poetry run black --check app
	cd apps/api && poetry run ruff check app

lint-fix:
	@echo "Auto-fixing backend lint issues..."
	cd apps/api && poetry run black app
	cd apps/api && poetry run ruff check --fix app

docker-up:
	@echo "Starting Docker services..."
	docker compose up -d
	@echo "Services started:"
	@echo "  - Frontend: http://localhost:3000"
	@echo "  - Backend: http://localhost:8000"
	@echo "  - API docs: http://localhost:8000/docs"

docker-down:
	@echo "Stopping Docker services..."
	docker compose down

docker-logs:
	@echo "Tailing Docker logs..."
	docker compose logs -f

docker-build:
	@echo "Rebuilding Docker images..."
	docker compose build --no-cache

docker-restart:
	@echo "Restarting Docker services..."
	docker compose restart

migrate:
	@echo "Running Alembic migrations..."
	cd apps/api && poetry run alembic upgrade head

migrate-create:
	@echo "Creating a new Alembic revision..."
	@read -p "Migration description: " desc; \
	cd apps/api && poetry run alembic revision --autogenerate -m "$$desc"

migrate-down:
	@echo "Rolling back one Alembic revision..."
	cd apps/api && poetry run alembic downgrade -1

db-reset:
	@echo "WARNING: this removes Docker database volumes."
	@read -p "Continue? [yes/no]: " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		docker compose down -v; \
		docker compose up -d postgres; \
		echo "Database reset complete."; \
	else \
		echo "Cancelled."; \
	fi

clean:
	@echo "Cleaning temporary files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".DS_Store" -delete 2>/dev/null || true
	rm -rf apps/api/.pytest_cache
	rm -rf apps/api/htmlcov

api-docs:
	@echo "Generating OpenAPI schema..."
	cd apps/api && poetry run python -c "import json; from app.main import app; json.dump(app.openapi(), open('openapi.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)"

shell:
	@echo "Opening API container shell..."
	docker compose exec api /bin/bash

psql:
	@echo "Opening PostgreSQL shell..."
	docker compose exec postgres psql -U postgres -d math_analysis

redis-cli:
	@echo "Opening Redis CLI..."
	docker compose exec redis redis-cli

.DEFAULT_GOAL := help
