.PHONY: install dev test lint seed db-migrate db-upgrade monitor clean

# Windows 用户提示：本 Makefile 依赖 bash/make（WSL / Git Bash / Cygwin 可用）。
# 若使用原生 PowerShell，请直接用如下命令：
#   docker compose -f deploy/docker-compose.yml up -d mysql redis milvus
#   cd backend && python -m app.db.seed
#   cd backend && uvicorn app.main:app --reload --port 8000
#   cd frontend && npm run dev

PY ?= python
PIP ?= pip

install:
	cd backend && $(PIP) install -e ".[dev]" && cd .. && cd frontend && npm install

dev:
	docker compose -f deploy/docker-compose.yml up -d mysql redis milvus
	cd backend && $(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
	cd frontend && npm run dev

test:
	cd backend && $(PY) -m pytest
	cd frontend && npx vitest run

lint:
	cd backend && $(PY) -m ruff check app tests
	cd frontend && npx eslint src

seed:
	cd backend && $(PY) -m app.db.seed

db-migrate:
	cd backend && alembic revision --autogenerate -m "$(MSG)"

db-upgrade:
	cd backend && alembic upgrade head

monitor:
	docker compose -f deploy/docker-compose.monitor.yml up -d

clean:
	cd backend && find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
