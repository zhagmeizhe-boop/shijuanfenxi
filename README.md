# 小学数学分班考试卷六维分析系统

> 智能试卷分析报告生成平台

## 项目简介

本系统是一个面向教育机构的智能试卷分析平台，通过 OCR 识别、智能解析和六维评分模型，自动生成试卷分析报告。

## 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+

### 一键启动

```bash
# 1. 配置环境变量
cp .env.example .env

# 2. 启动所有服务
docker-compose up -d

# 3. 访问服务
# - 前端: http://localhost:3000
# - 后端 API: http://localhost:8000
# - API 文档: http://localhost:8000/docs
```

### 本地开发

```bash
# 前端
cd apps/web
pnpm install
pnpm dev

# 后端
cd apps/api
poetry install
poetry run uvicorn app.main:app --reload
```

## 目录结构

```
.
├── apps/
│   ├── web/           # Next.js 前端
│   └── api/           # FastAPI 后端
├── packages/
│   └── shared/        # 共享代码
├── docs/              # 文档
├── scripts/           # 脚本
├── docker-compose.yml
└── README.md
```

## 技术栈

- **前端**: Next.js 14 + TypeScript + Tailwind CSS
- **后端**: FastAPI + Python 3.11
- **数据库**: PostgreSQL + Redis
- **任务队列**: Celery
- **部署**: Docker Compose

## 许可证

MIT
