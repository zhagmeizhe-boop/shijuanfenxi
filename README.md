# 小学数学试卷六维分析系统

智能试卷分析与报告生成平台。

## 快速启动

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+

### 一键启动

```bash
# 1. 准备环境变量
cp .env.example .env

# 2. 启动全部服务
docker compose up -d --build

# 3. 访问服务
# - 前端: http://localhost:3000
# - 后端 API: http://localhost:8000
# - API 文档: http://localhost:8000/docs
```

## 本地开发

当前仓库的本地开发主路径是：

- 前端使用 `npm + Vite`
- 后端使用 `apps/api/venv`
- 本地默认数据库是 SQLite
- 后台分析依赖 Redis + Celery Worker

### 1. 启动 Redis

```powershell
docker compose up -d redis
```

### 2. 启动后端 API

```powershell
cd apps/api
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动 Celery Worker

```powershell
cd apps/api
.\venv\Scripts\celery.exe -A app.tasks.celery_app:celery worker --loglevel=info
```

说明：

- 旧写法 `.\venv\Scripts\celery.exe -A app.tasks.celery_app worker --loglevel=info` 现在也兼容。
- Windows 下不需要手工加 `--pool=solo`，代码已自动处理。

### 4. 启动前端

```powershell
cd apps/web
npm install
npm run dev
```

### 本地访问地址

- 前端: `http://localhost:3000`
- 后端 API: `http://localhost:8000`
- API 文档: `http://localhost:8000/docs`

## 目录结构

```text
.
|-- apps/
|   |-- web/   # React + Vite 前端
|   `-- api/   # FastAPI 后端
|-- docs/
|-- scripts/
|-- docker-compose.yml
`-- README.md
```

## 技术栈

- 前端: React + Vite + TypeScript + Tailwind CSS
- 后端: FastAPI + Python
- 本地存储: SQLite
- 容器部署: PostgreSQL + Redis + Celery + Docker Compose

## License

MIT
