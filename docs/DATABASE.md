# 数据库设计文档

> 六维分析报告系统数据库设计

## 概述

本文档描述了六维分析报告系统的数据库设计，包括表结构、字段定义、索引设计和关系图。

## 技术选型

- **开发环境**: SQLite (轻量级，无需配置)
- **生产环境**: PostgreSQL (高性能，支持并发)
- **ORM**: SQLAlchemy 2.0+

## 核心表结构

### 1. papers 表（试卷表）

存储试卷基本信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| title | VARCHAR(200) | NOT NULL | 试卷标题 |
| file_path | VARCHAR(500) | | 文件存储路径 |
| status | VARCHAR(20) | DEFAULT 'uploaded' | 状态 |
| total_score | INTEGER | | 试卷总分 |
| question_count | INTEGER | | 题目数量 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

### 2. questions 表（题目表）

存储试卷中的题目信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| paper_id | VARCHAR(36) | FOREIGN KEY | 试卷ID |
| question_no | VARCHAR(20) | NOT NULL | 题号 |
| content | TEXT | | 题目内容 |
| score | INTEGER | | 分值 |
| question_type | VARCHAR(30) | | 题型 |
| features | JSON | | 特征数据 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

### 3. dimension_scores 表（维度分数表）

存储每道题目的维度评分结果。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| paper_id | VARCHAR(36) | FOREIGN KEY | 试卷ID |
| question_id | VARCHAR(36) | FOREIGN KEY | 题目ID |
| dimension_code | VARCHAR(10) | NOT NULL | 维度代码 |
| score | DECIMAL(3,1) | NOT NULL | 维度分数（0-10） |
| level | INTEGER | NOT NULL | 等级（1-5） |
| evidence | TEXT | | 评分依据 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

### 4. reports 表（报告表）

存储完整的分析报告。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PRIMARY KEY | UUID 主键 |
| paper_id | VARCHAR(36) | FOREIGN KEY | 试卷ID |
| status | VARCHAR(20) | DEFAULT 'generating' | 状态 |
| dimensions | JSON | | 维度分数汇总 |
| difficulty_position | JSON | | 难度定位 |
| overall_summary | TEXT | | 总体评价 |
| recommendations | JSON | | 学习建议 |
| pdf_path | VARCHAR(500) | | PDF 文件路径 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

## 初始化脚本

### SQLite 初始化

```sql
-- 创建表
CREATE TABLE papers (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    file_path VARCHAR(500),
    file_size INTEGER,
    file_hash VARCHAR(64),
    status VARCHAR(20) DEFAULT 'uploaded',
    total_score INTEGER,
    question_count INTEGER,
    grade VARCHAR(20),
    subject VARCHAR(20),
    uploaded_by VARCHAR(36),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE questions (
    id VARCHAR(36) PRIMARY KEY,
    paper_id VARCHAR(36) NOT NULL,
    question_no VARCHAR(20) NOT NULL,
    content TEXT,
    answer TEXT,
    score INTEGER,
    question_type VARCHAR(30),
    difficulty VARCHAR(20),
    knowledge_points JSON,
    features JSON,
    page_number INTEGER,
    bounding_box JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id)
);

CREATE TABLE dimension_scores (
    id VARCHAR(36) PRIMARY KEY,
    paper_id VARCHAR(36) NOT NULL,
    question_id VARCHAR(36) NOT NULL,
    dimension_code VARCHAR(10) NOT NULL,
    score DECIMAL(3,1) NOT NULL,
    level INTEGER NOT NULL,
    level_label VARCHAR(20),
    evidence TEXT,
    features JSON,
    applicable BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id),
    FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE TABLE reports (
    id VARCHAR(36) PRIMARY KEY,
    paper_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) DEFAULT 'generating',
    dimensions JSON,
    dimension_distribution JSON,
    difficulty_position JSON,
    benchmark_comparisons JSON,
    knowledge_points JSON,
    representative_questions JSON,
    overall_summary TEXT,
    recommendations JSON,
    pdf_path VARCHAR(500),
    pdf_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id)
);

-- 创建索引
CREATE INDEX idx_papers_status ON papers(status);
CREATE INDEX idx_papers_created_at ON papers(created_at);
CREATE INDEX idx_questions_paper_id ON questions(paper_id);
CREATE INDEX idx_dim_scores_paper_id ON dimension_scores(paper_id);
CREATE INDEX idx_dim_scores_dimension ON dimension_scores(dimension_code);
CREATE INDEX idx_reports_paper_id ON reports(paper_id);
CREATE INDEX idx_reports_status ON reports(status);
```

## ER 图

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   users     │       │   papers    │       │  questions  │
├─────────────┤       ├─────────────┤       ├─────────────┤
│ id          │       │ id          │◀──────│ paper_id    │
│ username    │       │ title       │       │ id          │
│ email       │       │ file_path   │       │ content     │
│ password    │       │ status      │       │ question_no │
│ role        │       │ total_score │       └─────────────┘
│ created_at  │       │ question_count          │
└─────────────┘       │ uploaded_by             ▼
        │             │ created_at        ┌─────────────┐
        │             └─────────────┘     │ dimension_  │
        │                      │          │   scores    │
        │                      │          ├─────────────┤
        ▼                      ▼          │ id          │
  ┌─────────────┐       ┌─────────────┐ │ paper_id    │
  │    reports  │       │ upload_     │ │ question_id│
  ├─────────────┤       │   tasks     │ │ dimension_  │
  │ id          │       ├─────────────┤ │   code      │
  │ paper_id    │◀──────│ id          │ │ score       │
  │ status      │       │ paper_id    │ │ level       │
  │ dimensions  │       │ status      │ │ evidence    │
  │ difficulty  │       │ progress    │ └─────────────┘
  │ summary     │       │ error_msg   │
  │ pdf_path    │       │ created_at  │
  │ created_at  │       └─────────────┘
  └─────────────┘
```

## 性能优化建议

1. **分区表**: 对于大量历史数据，可按时间分区
2. **读写分离**: 生产环境建议主从复制
3. **缓存**: 热点数据使用 Redis 缓存
4. **索引优化**: 根据查询模式调整索引

## 备份策略

```bash
# 手动备份
pg_dump math_report > backup_$(date +%Y%m%d).sql

# 自动备份（crontab）
0 2 * * * pg_dump math_report > /backup/math_report_$(date +\%Y\%m\%d).sql
```

---

**文档版本**: v1.0.0  
**最后更新**: 2024-04-07
