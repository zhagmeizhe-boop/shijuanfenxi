# 数据库设计文档

> 六维分析报告系统数据库设计

## 概述

本文档描述了六维分析报告系统的数据库设计，包括表结构、字段定义、索引设计和关系图。

## 技术选型

- **开发环境**: SQLite (轻量级，无需配置)
- **生产环境**: PostgreSQL (高性能，支持并发)
- **ORM**: SQLAlchemy 2.0+
- **迁移**: Alembic (可选)

## 数据库架构图

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│     users       │       │    papers       │       │   questions     │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │◀──────│ paper_id (FK)   │
│ username        │       │ title           │       │ id (PK)         │
│ email           │       │ file_path       │       │ content         │
│ created_at      │       │ status          │       │ question_no     │
└─────────────────┘       │ total_score     │       │ score           │
                          │ question_count  │       │ question_type   │
                          │ uploaded_by(FK) │──────▶│ features (JSON) │
                          │ created_at      │       │ created_at      │
                          └─────────────────┘       └─────────────────┘
                                    │                         │
                                    ▼                         ▼
                          ┌─────────────────┐       ┌─────────────────┐
                          │  dimension_scores        │   upload_tasks  │
                          ├─────────────────┤       ├─────────────────┤
                          │ id (PK)         │       │ id (PK)         │
                          │ paper_id (FK)   │◀──────│ paper_id (FK)   │
                          │ question_id(FK) │◀──────│ status          │
                          │ dimension_code  │       │ progress        │
                          │ score           │       │ error_message   │
                          │ level           │       │ created_at      │
                          │ evidence        │       │ updated_at      │
                          │ features (JSON) │       └─────────────────┘
                          │ created_at      │
                          └─────────────────┘
                                    │
                                    ▼
                          ┌─────────────────┐
                          │     reports     │
                          ├─────────────────┤
                          │ id (PK)         │
                          │ paper_id (FK)   │
                          │ status          │
                          │ dimensions(JSON)│
                          │ difficulty(JSON)│
                          │ summary         │
                          │ recommendations │
                          │ pdf_path        │
                          │ created_at      │
                          └─────────────────┘
```

## 表结构详细说明

### 1. users 表（用户表）

存储系统用户信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| username | VARCHAR(50) | UNIQUE, NOT NULL | 用户名 |
| email | VARCHAR(100) | UNIQUE | 邮箱 |
| password_hash | VARCHAR(255) | | 密码哈希 |
| role | VARCHAR(20) | DEFAULT 'user' | 角色：admin/user |
| status | VARCHAR(20) | DEFAULT 'active' | 状态 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | | 更新时间 |

**索引**:
- `idx_users_username` ON username
- `idx_users_email` ON email

### 2. papers 表（试卷表）

存储试卷基本信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| title | VARCHAR(200) | NOT NULL | 试卷标题 |
| file_path | VARCHAR(500) | | 文件存储路径 |
| file_size | INTEGER | | 文件大小（字节） |
| file_hash | VARCHAR(64) | | 文件 SHA256 |
| status | VARCHAR(20) | DEFAULT 'uploaded' | 状态 |
| total_score | INTEGER | | 试卷总分 |
| question_count | INTEGER | | 题目数量 |
| grade | VARCHAR(20) | | 年级 |
| subject | VARCHAR(20) | | 科目 |
| uploaded_by | VARCHAR(36) | FOREIGN KEY | 上传用户ID |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | | 更新时间 |
| completed_at | TIMESTAMP | | 完成时间 |

**状态说明**:
- `uploaded` - 已上传
- `processing` - 处理中
- `analyzed` - 已分析
- `failed` - 失败

**索引**:
- `idx_papers_status` ON status
- `idx_papers_uploaded_by` ON uploaded_by
- `idx_papers_created_at` ON created_at

### 3. questions 表（题目表）

存储试卷中的题目信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| paper_id | VARCHAR(36) | FOREIGN KEY, NOT NULL | 试卷ID |
| question_no | VARCHAR(20) | NOT NULL | 题号（如"一、1"） |
| content | TEXT | | 题目内容 |
| answer | TEXT | | 答案 |
| score | INTEGER | | 分值 |
| question_type | VARCHAR(30) | | 题型 |
| difficulty | VARCHAR(20) | | 难度 |
| knowledge_points | JSON | | 知识点列表 |
| features | JSON | | 特征数据 |
| page_number | INTEGER | | 所在页码 |
| bounding_box | JSON | | 位置坐标 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | | 更新时间 |

**题型说明**:
- `computation` - 计算题
- `choice` - 选择题
- `fill_blank` - 填空题
- `word_problem` - 应用题
- `geometry` - 几何题

**索引**:
- `idx_questions_paper_id` ON paper_id
- `idx_questions_question_no` ON question_no

### 4. dimension_scores 表（维度分数表）

存储每道题目的维度评分结果。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| paper_id | VARCHAR(36) | FOREIGN KEY, NOT NULL | 试卷ID |
| question_id | VARCHAR(36) | FOREIGN KEY, NOT NULL | 题目ID |
| dimension_code | VARCHAR(10) | NOT NULL | 维度代码 |
| score | DECIMAL(3,1) | NOT NULL | 维度分数（0-10） |
| level | INTEGER | NOT NULL | 等级（1-5） |
| level_label | VARCHAR(20) | | 等级标签 |
| evidence | TEXT | | 评分依据 |
| features | JSON | | 特征数据 |
| applicable | BOOLEAN | DEFAULT true | 是否适用 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

**维度代码**:
- `dim1` - 计算熟练度
- `dim2` - 概念清晰度
- `dim3` - 逻辑推理力
- `dim4` - 空间想象力
- `dim5` - 应用实践力
- `dim6` - 创新思维力

**索引**:
- `idx_dim_scores_paper_id` ON paper_id
- `idx_dim_scores_question_id` ON question_id
- `idx_dim_scores_dimension` ON dimension_code
- `idx_dim_scores_paper_dim` ON (paper_id, dimension_code)

### 5. reports 表（报告表）

存储完整的分析报告。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| paper_id | VARCHAR(36) | FOREIGN KEY, NOT NULL | 试卷ID |
| status | VARCHAR(20) | DEFAULT 'generating' | 状态 |
| dimensions | JSON | | 维度分数汇总 |
| dimension_distribution | JSON | | 维度分布 |
| difficulty_position | JSON | | 难度定位 |
| benchmark_comparisons | JSON | | 基准对比 |
| knowledge_points | JSON | | 知识点分析 |
| representative_questions | JSON | | 代表性题目 |
| overall_summary | TEXT | | 总体评价 |
| recommendations | JSON | | 学习建议 |
| pdf_path | VARCHAR(500) | | PDF 文件路径 |
| pdf_url | VARCHAR(500) | | PDF 下载链接 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | | 更新时间 |
| completed_at | TIMESTAMP | | 完成时间 |

**索引**:
- `idx_reports_paper_id` ON paper_id
- `idx_reports_status` ON status
- `idx_reports_created_at` ON created_at

### 6. upload_tasks 表（上传任务表）

追踪文件上传和处理任务。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| paper_id | VARCHAR(36) | FOREIGN KEY | 试卷ID |
| file_name | VARCHAR(255) | | 文件名 |
| file_size | INTEGER | | 文件大小 |
| file_hash | VARCHAR(64) | | 文件哈希 |
| status | VARCHAR(20) | DEFAULT 'pending' | 状态 |
| progress | INTEGER | DEFAULT 0 | 进度百分比 |
| stage | VARCHAR(50) | | 当前阶段 |
| error_message | TEXT | | 错误信息 |
| error_details | JSON | | 错误详情 |
| started_at | TIMESTAMP | | 开始时间 |
| completed_at | TIMESTAMP | | 完成时间 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | | 更新时间 |

**任务状态**:
- `pending` - 等待处理
- `uploading` - 上传中
- `processing` - 处理中
- `analyzing` - 分析中
- `completed` - 完成
- `failed` - 失败

**处理阶段**:
- `file_validation` - 文件验证
- `file_upload` - 文件上传
- `ocr_recognition` - OCR 识别
- "}