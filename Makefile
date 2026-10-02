# OmniStock —— 常用命令集中入口
#
#   make help          查看所有目标
#   make test          跑后端测试
#   make seed          写入演示数据
#
# Windows 用户请在 Git Bash 或 WSL 中执行。

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := backend
WEB      := web
PY       ?= python
COMPOSE  ?= docker compose
BASE_URL ?= http://127.0.0.1:8000

.PHONY: help
help: ## 显示所有可用命令
	@echo "OmniStock 命令列表"
	@echo ""
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ------------------------------------------------------------------ 本地开发
.PHONY: install
install: ## 安装后端与前端依赖
	cd $(BACKEND) && $(PY) -m pip install -r requirements.txt
	cd $(WEB) && npm install

.PHONY: dev-api
dev-api: ## 启动后端开发服务器（热重载）
	cd $(BACKEND) && $(PY) -m uvicorn app.main:app --reload --port 8000

.PHONY: dev-web
dev-web: ## 启动前端开发服务器
	cd $(WEB) && npm run dev

.PHONY: migrate
migrate: ## 执行数据库迁移到最新版本
	cd $(BACKEND) && $(PY) -m alembic upgrade head

.PHONY: revision
revision: ## 生成新迁移，用法：make revision m="add xxx table"
	@test -n "$(m)" || { echo '请提供消息：make revision m="add xxx table"'; exit 1; }
	cd $(BACKEND) && $(PY) -m alembic revision --autogenerate -m "$(m)"

.PHONY: downgrade
downgrade: ## 回退一个迁移版本
	cd $(BACKEND) && $(PY) -m alembic downgrade -1

.PHONY: seed
seed: ## 写入演示种子数据（可重复执行）
	cd $(BACKEND) && $(PY) -m app.seed

# ---------------------------------------------------------------------- 测试
.PHONY: test
test: ## 运行后端测试
	cd $(BACKEND) && $(PY) -m pytest tests -q

.PHONY: test-verbose
test-verbose: ## 运行后端测试并显示每个用例
	cd $(BACKEND) && $(PY) -m pytest tests -v

.PHONY: lint
lint: ## 前端类型检查
	cd $(WEB) && npm run type-check

.PHONY: check
check: test lint ## 测试 + 类型检查

# --------------------------------------------------------------------- Docker
.PHONY: up
up: ## 构建并启动（SQLite）
	@test -f .env || { echo "缺少 .env，正在从模板复制（请随后修改密钥）"; cp .env.example .env; }
	$(COMPOSE) up -d --build

.PHONY: up-pg
up-pg: ## 构建并启动（PostgreSQL，推荐）
	@test -f .env || { echo "缺少 .env，正在从模板复制"; cp .env.example .env; }
	$(COMPOSE) --profile postgres up -d --build

.PHONY: down
down: ## 停止并移除容器（保留数据卷）
	$(COMPOSE) down

.PHONY: down-clean
down-clean: ## 停止并删除数据卷（⚠️ 会清空数据库）
	$(COMPOSE) down -v

.PHONY: ps
ps: ## 查看容器状态
	$(COMPOSE) ps

.PHONY: logs
logs: ## 跟踪所有容器日志
	$(COMPOSE) logs -f --tail=100

.PHONY: logs-api
logs-api: ## 跟踪后端日志
	$(COMPOSE) logs -f --tail=100 api

.PHONY: shell-api
shell-api: ## 进入后端容器
	$(COMPOSE) exec api /bin/bash

# --------------------------------------------------------------------- 运维
.PHONY: health
health: ## 探活
	curl -fsS $(BASE_URL)/healthz && echo

.PHONY: docs
docs: ## 打开接口文档（需 EXPOSE_DOCS=true）
	@echo "$(BASE_URL)/docs"
