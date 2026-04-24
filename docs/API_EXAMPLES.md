# 小学数学分班考试卷六维分析系统 - API 请求示例

本文档提供 API 请求示例，用于测试和开发。

## 基础信息

- 基础 URL: `http://localhost:8000`
- API 版本: `/api/v1`

## 1. 健康检查

### 请求

```bash
curl -X GET "http://localhost:8000/health"
```

### 响应

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "timestamp": "2024-01-15T08:30:00"
}
```

## 2. 分析试卷

### 请求

```bash
curl -X POST "http://localhost:8000/api/v1/papers/analyze" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/your/paper.pdf" \
  -F "paper_name=2024年五年级数学分班考试" \
  -F "grade=五年级" \
  -F "subject=数学" \
  -F "source=XX教育集团"
```

### 响应

```json
{
  "paper_id": "550e8400-e29b-41d4-a716-446655440000",
  "parse_status": "pending",
  "message": "试卷上传成功，正在分析中...",
  "estimated_seconds": 30
}
```

## 3. 查询试卷状态

### 请求

```bash
curl -X GET "http://localhost:8000/api/v1/papers/550e8400-e29b-41d4-a716-446655440000/status"
```

### 响应

```json
{
  "paper_id": "550e8400-e29b-41d4-a716-446655440000",
  "parse_status": "parse_success",
  "parse_confidence": 0.92,
  "need_manual_review": false,
  "total_question_count": 10,
  "total_score": 100.0,
  "created_at": "2024-01-15T08:30:00",
  "updated_at": "2024-01-15T08:35:42"
}
```

## 4. 获取试卷解析结果

### 请求

```bash
curl -X GET "http://localhost:8000/api/v1/papers/550e8400-e29b-41d4-a716-446655440000/result"
```

### 响应

详见 `apps/api/data/mock_paper_example.json`

简化响应示例：

```json
{
  "paper_id": "550e8400-e29b-41d4-a716-446655440000",
  "paper_name": "2024年小学五年级数学分班考试",
  "total_question_count": 10,
  "total_score": 100.0,
  "page_count": 6,
  "parse_status": "parse_success",
  "parse_confidence": 0.92,
  "need_manual_review": false,
  "questions": [
    {
      "question_no": "1",
      "question_type": "fill_blank",
      "raw_text": "3/4 + 2/5 = ______",
      "score": 4.0,
      "is_optional": false,
      "include_in_main_score": true,
      "parse_confidence": 0.95,
      "applicable_dims": ["dim1"],
      "sub_questions": []
    }
    // ... 更多题目
  ],
  "file_type": "pdf",
  "source_file_url": "/uploads/paper-550e8400-e29b-41d4-a716-446655440000/original.pdf",
  "created_at": "2024-01-15T08:30:00"
}
```

## 使用 Python 请求示例

```python
import requests

# 分析试卷
url = "http://localhost:8000/api/v1/papers/analyze"

with open("/path/to/paper.pdf", "rb") as f:
    files = {"file": ("paper.pdf", f, "application/pdf")}
    data = {
        "paper_name": "2024年五年级数学分班考试",
        "grade": "五年级",
        "subject": "数学",
    }
    response = requests.post(url, files=files, data=data)

print(response.json())
```

## 错误处理

### 400 Bad Request

```json
{
  "code": "VALIDATION_ERROR",
  "message": "文件大小超过限制: 55.00MB (最大: 50MB)",
  "details": null
}
```

### 404 Not Found

```json
{
  "code": "NOT_FOUND",
  "message": "试卷不存在: 550e8400-e29b-41d4-a716-446655440000",
  "details": null
}
```

### 500 Internal Server Error

```json
{
  "code": "INTERNAL_ERROR",
  "message": "服务器内部错误",
  "details": null
}
```
