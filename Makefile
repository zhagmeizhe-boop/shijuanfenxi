# Math Analysis System - Makefile

.PHONY: help install dev build test clean docker-up docker-down docker-logs migrate

# 默认命令
help:
	@echo "Math Analysis System - 可用命令:"
	@echo ""
	@echo "  开发命令:"
	@echo "    make install          - 安装依赖"
	@echo "    make dev              - 启动开发环境"
	@echo "    make test             - 运行测试"
	@echo "    make lint             - 运行代码检查"
	@echo ""
	@echo "  Docker 命令:"
	@echo "    make docker-up        - 启动所有 Docker 服务"
	@echo "    make docker-down      - 停止所有 Docker 服务"
	@echo "    make docker-logs      - 查看 Docker 日志"
	@echo "    make docker-build     - 重新构建 Docker 镜像"
	@echo ""
	@echo "  数据库命令:"
	@echo "    make migrate          - 运行数据库迁移"
	@echo "    make migrate-create   - 创建新的迁移版本"
	@echo "    make db-reset         - 重置数据库"
	@echo ""
	@echo "  其他命令:"
	@echo "    make clean            - 清理临时文件"
	@echo "    make api-docs         - 生成 API 文档"
	@echo ""

# ==================== 开发命令 ====================

install:
	@echo "📦 安装后端依赖..."
	cd apps/api && poetry install
	@echo "📦 安装前端依赖..."
	cd apps/web && pnpm install

dev:
	@echo "🚀 启动开发环境..."
	@echo "请使用以下命令分别启动前后端:"
	@echo "  终端1: cd apps/api && poetry run uvicorn app.main:app --reload"
	@echo "  终端2: cd apps/web && pnpm dev"

test:
	@echo "🧪 运行测试..."
	cd apps/api && poetry run pytest -v

lint:
	@echo "🔍 运行代码检查..."
	cd apps/api && poetry run black --check app
	cd apps/api && poetry run ruff check app

lint-fix:
	@echo "🔧 自动修复代码问题..."
	cd apps/api && poetry run black app
	cd apps/api && poetry run ruff check --fix app

# ==================== Docker 命令 ====================

docker-up:
	@echo "🐳 启动 Docker 服务..."
	docker-compose up -d
	@echo "✅ 服务已启动!"
	@echo "  - 前端: http://localhost:3000"
	@echo "  - 后端: http://localhost:8000"
	@echo "  - API文档: http://localhost:8000/docs"

docker-down:
	@echo "🛑 停止 Docker 服务..."
	docker-compose down
	@echo "✅ 服务已停止"

docker-logs:
	@echo "📜 查看 Docker 日志..."
	docker-compose logs -f

docker-build:
	@echo "🔨 重新构建 Docker 镜像..."
	docker-compose build --no-cache

docker-restart:
	@echo "🔄 重启 Docker 服务..."
	docker-compose restart

# ==================== 数据库命令 ====================

migrate:
	@echo "🗄️  运行数据库迁移..."
	cd apps/api && poetry run alembic upgrade head

migrate-create:
	@echo "📝 创建新的迁移版本..."
	@read -p "输入迁移描述: " desc; \
	cd apps/api && poetry run alembic revision --autogenerate -m "$$desc"

migrate-down:
	@echo "⏪ 回滚上一个迁移..."
	cd apps/api && poetry run alembic downgrade -1

db-reset:
	@echo "⚠️  警告: 这将删除所有数据!"
	@read -p "确认重置数据库? [yes/no]: " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		docker-compose down -v; \
		docker-compose up -d postgres; \
		echo "✅ 数据库已重置"; \
	else \
		echo "操作已取消"; \
	fi

# ==================== 其他命令 ====================

clean:
	@echo "🧹 清理临时文件..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".DS_Store" -delete 2>/dev/null || true
	rm -rf apps/api/.pytest_cache
	rm -rf apps/api/htmlcov
	@echo "✅ 清理完成"

api-docs:
	@echo "📚 生成 API 文档..."
	cd apps/api && poetry run python -c "
import json
from app.main import app
with open('openapi.json', 'w') as f:
    json.dump(app.openapi(), f, indent=2)
print('API 文档已生成: openapi.json')
"

shell:
	@echo "🐚 进入 API 容器 shell..."
	docker-compose exec api /bin/bash

psql:
	@echo "🐘 进入 PostgreSQL..."
	docker-compose exec postgres psql -U postgres -d math_analysis

redis-cli:
	@echo "🔄 进入 Redis..."
	docker-compose exec redis redis-cli

# 帮助命令
.DEFAULT_GOAL := help
