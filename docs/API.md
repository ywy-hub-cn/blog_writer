# Blog-Writer API 接口文档

> 完整的 REST API 接口说明，包含请求/响应示例。
> 最后更新：2026-08-12
> Base URL: `http://localhost:8000`（本地）/ `https://api.yourcompany.com`（生产）

---

## 目录

1. [通用约定](#1-通用约定)
2. [认证接口](#2-认证接口)
3. [品牌接口](#3-品牌接口)
4. [任务接口](#4-任务接口)
5. [节点接口](#5-节点接口)
6. [配置接口](#6-配置接口)
7. [管理员接口](#7-管理员接口)
8. [Webhook 接口](#8-webhook-接口)
9. [系统接口](#9-系统接口)
10. [错误码](#10-错误码)

---

## 1. 通用约定

### 1.1 基础信息

- **API 版本**：v1（主版本），兼容 `/api/*` 旧路径
- **请求格式**：`application/json`（文件上传用 `multipart/form-data`）
- **响应格式**：统一包装为 `{code, message, data, timestamp}`
- **字符编码**：UTF-8
- **字段命名**：默认 `snake_case`，设置 `RESPONSE_CASE=camel` 后转为 `camelCase`

### 1.2 统一响应格式

所有 API 响应（除流式/附件/metrics）都包装为：

```json
{
  "code": 0,
  "message": "success",
  "data": { ... },
  "timestamp": 1691234567890
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务码，0=成功，非0=失败 |
| `message` | string | 提示信息 |
| `data` | object/array | 业务数据 |
| `timestamp` | long | 服务器时间戳（毫秒） |

### 1.3 认证方式

| 方式 | 说明 | 适用接口 |
|------|------|----------|
| 免登录 | 自动返回默认 admin 用户 | 任务接口、品牌接口 |
| Bearer Token | `Authorization: Bearer <jwt_token>` | 需登录的接口 |
| API Key | `X-API-Key: <token>` | 后端服务对接 |

任务接口和品牌接口**免登录**，未登录时自动使用默认运营用户（`operator`）。

### 1.4 请求示例（cURL）

```bash
# 免登录调用
curl http://localhost:8000/api/tasks

# 带 Token 调用
curl -H "Authorization: Bearer eyJ..." http://localhost:8000/api/admin/config

# API Key 调用
curl -H "X-API-Key: dev-token-local" http://localhost:8000/api/tasks
```

### 1.5 分页参数

列表接口通用分页参数：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页数量 |
| `limit` | int | 20 | 限制数量（部分接口） |
| `offset` | int | 0 | 偏移量（部分接口） |

---

## 2. 认证接口

### 2.1 登录

**POST** `/api/v1/auth/login`

请求体：
```json
{
  "username": "admin",
  "password": "admin123"
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "user": {
      "user_id": "admin",
      "role": "admin",
      "is_admin": true
    },
    "expires_at": 1691234567
  }
}
```

### 2.2 验证 Token

**GET** `/api/v1/auth/verify`

请求头：`Authorization: Bearer <token>`

响应：
```json
{
  "code": 0,
  "data": {
    "valid": true,
    "user_id": "admin",
    "role": "admin",
    "expires_at": 1691234567
  }
}
```

### 2.3 登出

**POST** `/api/v1/auth/logout`

请求头：`Authorization: Bearer <token>`

### 2.4 修改密码

**POST** `/api/v1/auth/change-password`

请求体：
```json
{
  "old_password": "admin123",
  "new_password": "new-password"
}
```

### 2.5 修改运营密码

**POST** `/api/v1/auth/change-operator-password`

请求体：
```json
{
  "new_password": "new-operator-password"
}
```

### 2.6 调试信息

**GET** `/api/v1/auth/debug`

返回当前认证配置信息（开发环境用）。

---

## 3. 品牌接口

> 品牌接口**免登录**，运营人员可直接使用。

### 3.1 获取品牌列表

**GET** `/api/v1/brands`

响应：
```json
{
  "code": 0,
  "data": {
    "brands": [
      {
        "brand_id": "sms-boosting",
        "display_name": "SMS Boosting",
        "inner_path": "./brands/sms-boosting",
        "created_at": "2026-08-12T10:00:00",
        "updated_at": "2026-08-12T10:00:00"
      }
    ],
    "total": 1
  }
}
```

### 3.2 上传品牌资料

**POST** `/api/v1/brands/upload`

Content-Type: `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `display_name` | string | 是 | 品牌中文显示名，如"SMS Boosting" |
| `files` | file[] | 是 | 文件数组，支持 `.md`/`.txt`，单文件≤10MB |

请求示例（cURL）：
```bash
curl -X POST http://localhost:8000/api/brands/upload \
  -F "display_name=SMS Boosting" \
  -F "files=@brand-info.md" \
  -F "files=@products.md"
```

响应：
```json
{
  "code": 0,
  "message": "上传成功",
  "data": {
    "brand_id": "sms-boosting",
    "display_name": "SMS Boosting",
    "inner_path": "./brands/sms-boosting",
    "files": ["brand-info.md", "products.md"],
    "file_count": 2
  }
}
```

**说明**：
- 中文名称自动转拼音生成 `brand_id`（如"测试品牌"→`ceshipinpai`）
- 重复 `brand_id` 直接覆盖目录，不做版本备份
- 重名文件自动加 `_1`/`_2` 后缀
- 仅允许 `.md`/`.txt` 后缀

---

## 4. 任务接口

> 任务接口**免登录**，未登录时自动使用默认运营用户。

### 4.1 启动任务

**POST** `/api/v1/tasks/start`

请求体：
```json
{
  "brand_path": "./brands/sms-boosting",
  "keywords": "sms api, sms gateway, bulk sms",
  "user_note": "重点强调API稳定性",
  "mode": "auto",
  "brand_site_url": "https://smsboosting.com",
  "model": "default",
  "temperature": 0.7,
  "max_tokens": 4096,
  "callback_url": "https://yourcompany.com/callback",
  "callback_secret": "your-secret",
  "forbidden_whitelist": ["竞品词1", "竞品词2"]
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `brand_path` | string | **是** | - | 品牌目录路径，从品牌列表接口获取 |
| `keywords` | string | **是** | - | 写作关键词，逗号分隔 |
| `user_note` | string | 否 | "" | 用户备注/特殊要求 |
| `mode` | string | 否 | "auto" | 工作流模式：auto/supervised/manual |
| `brand_site_url` | string | 否 | "" | 品牌官网URL |
| `model` | string | 否 | "default" | 使用的模型配置名 |
| `temperature` | float | 否 | - | 采样温度，0-2 |
| `max_tokens` | int | 否 | - | 最大生成token |
| `callback_url` | string | 否 | - | Webhook 回调地址 |
| `callback_secret` | string | 否 | - | Webhook 签名密钥 |
| `forbidden_whitelist` | string[] | 否 | - | 本次任务禁用词白名单 |
| `step_files` | string[] | 否 | - | 自定义步骤列表（高级） |
| `resume_from` | string | 否 | - | 从指定节点续跑（高级） |
| `task_id` | string | 否 | - | 指定任务ID（高级） |

响应：
```json
{
  "code": 0,
  "message": "任务已启动",
  "data": {
    "task_id": "task_20260812_100748_75321e",
    "status": "running",
    "current_step": 1,
    "total_steps": 16,
    "created_at": "2026-08-12T10:07:48"
  }
}
```

### 4.2 获取任务列表

**GET** `/api/v1/tasks?page=1&page_size=20&status=running`

| 参数 | 类型 | 说明 |
|------|------|------|
| `page` | int | 页码，默认1 |
| `page_size` | int | 每页数量，默认20 |
| `status` | string | 按状态筛选：running/completed/failed/cancelled/paused |

响应：
```json
{
  "code": 0,
  "data": {
    "tasks": [
      {
        "task_id": "task_20260812_100748_75321e",
        "status": "failed",
        "current_step": 5,
        "total_steps": 16,
        "keywords": "sms api",
        "brand_path": "./brands/sms-boosting",
        "created_at": "2026-08-12T10:07:48",
        "updated_at": "2026-08-12T10:15:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  }
}
```

### 4.3 获取任务详情

**GET** `/api/v1/tasks/{task_id}`

响应：
```json
{
  "code": 0,
  "data": {
    "task_id": "task_20260812_100748_75321e",
    "status": "running",
    "current_step": 10,
    "total_steps": 16,
    "current_step_file": "S007-visual.json",
    "completed_steps": ["S000-startup.json", "S001-bid-infer.json"],
    "keywords": "sms api",
    "brand_path": "./brands/sms-boosting",
    "mode": "auto",
    "owner_id": "operator",
    "created_at": "2026-08-12T10:07:48",
    "updated_at": "2026-08-12T10:30:00",
    "token_usage": {
      "total_tokens": 1691085,
      "prompt_tokens": 1580000,
      "completion_tokens": 111085
    },
    "error": null,
    "log": ["[10:07:48] 任务启动", "..."]
  }
}
```

### 4.4 获取任务日志

**GET** `/api/v1/tasks/{task_id}/logs?limit=100&offset=0`

| 参数 | 类型 | 说明 |
|------|------|------|
| `limit` | int | 返回条数，默认100 |
| `offset` | int | 偏移量，默认0 |

响应：
```json
{
  "code": 0,
  "data": {
    "logs": ["[10:07:48] 任务启动", "[10:07:50] Step 1/16: S000-startup.json"],
    "total": 500,
    "limit": 100,
    "offset": 0
  }
}
```

### 4.5 暂停任务

**POST** `/api/v1/tasks/{task_id}/pause`

响应：
```json
{
  "code": 0,
  "message": "任务已暂停",
  "data": { "task_id": "...", "status": "paused" }
}
```

### 4.6 恢复任务

**POST** `/api/v1/tasks/{task_id}/resume`

响应：
```json
{
  "code": 0,
  "message": "任务已恢复",
  "data": { "task_id": "...", "status": "running" }
}
```

### 4.7 取消任务

**POST** `/api/v1/tasks/{task_id}/cancel`

响应：
```json
{
  "code": 0,
  "message": "任务已取消",
  "data": { "task_id": "...", "status": "cancelled" }
}
```

### 4.8 从指定节点续跑

**POST** `/api/v1/tasks/{task_id}/resume-from`

请求体：
```json
{
  "node_file": "S007-visual.json",
  "brand_path": "./brands/sms-boosting",
  "keywords": "sms api",
  "mode": "auto"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_file` | string | **是** | 从哪个节点继续，如"S007-visual.json" |
| `brand_path` | string | 否 | 品牌路径（可选，默认用原任务的） |
| `keywords` | string | 否 | 关键词（可选） |
| `mode` | string | 否 | 模式（可选） |

响应：
```json
{
  "code": 0,
  "message": "续跑已启动",
  "data": {
    "task_id": "task_20260812_100748_75321e",
    "status": "running",
    "resume_from": "S007-visual.json"
  }
}
```

**说明**：
- 已完成的步骤不会重复执行
- 从 `node_file` 开始继续执行后续步骤
- 支持 cancelled/failed/paused 状态的任务续跑

### 4.9 从指定节点重跑

**POST** `/api/v1/tasks/{task_id}/rerun-from`

请求体：
```json
{
  "node_file": "S004-draft.json",
  "brand_path": "./brands/sms-boosting",
  "keywords": "sms api",
  "mode": "auto"
}
```

与 `resume-from` 的区别：
- `resume-from`：跳过已完成步骤，从指定节点**继续**
- `rerun-from`：从指定节点**重新运行**，忽略该节点及之后的已有结果

### 4.10 重试当前节点

**POST** `/api/v1/tasks/{task_id}/retry-node`

请求体：
```json
{
  "node_file": "S007-visual.json"
}
```

仅重试当前失败的节点，不影响其他步骤。

### 4.11 获取待审核列表

**GET** `/api/v1/tasks/reviews/pending`

响应：
```json
{
  "code": 0,
  "data": {
    "reviews": [
      {
        "task_id": "task_xxx",
        "step_file": "S001H-human-review-bid.json",
        "review_data": { ... },
        "created_at": "2026-08-12T10:00:00"
      }
    ],
    "total": 1
  }
}
```

### 4.12 提交审核决策

**POST** `/api/v1/tasks/{task_id}/review`

请求体：
```json
{
  "decision": "approve",
  "modifications": { "comment": "审核通过" }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `decision` | string | **是** | 决策：approve/reject/modify/retry |
| `modifications` | object | 否 | 修改意见或备注 |

---

## 5. 节点接口

### 5.1 获取节点列表

**GET** `/api/v1/nodes`

响应：
```json
{
  "code": 0,
  "data": {
    "nodes": [
      {
        "id": "step.blog.writer.startup",
        "seq": 0,
        "name": "启动初始化",
        "file": "S000-startup.json",
        "kind": "agent_action"
      }
    ],
    "total": 16
  }
}
```

### 5.2 获取节点详情

**GET** `/api/v1/nodes/{node_id}`

响应：
```json
{
  "code": 0,
  "data": {
    "id": "step.blog.writer.publish_wp",
    "seq": 11,
    "name": "WordPress 发布",
    "kind": "agent_action",
    "resources": { ... },
    "constraints": { ... },
    "actions": [ ... ],
    "checks": [ ... ]
  }
}
```

### 5.3 验证节点

**POST** `/api/v1/nodes/{node_id}/validate`

验证节点定义是否合法，返回校验结果。

---

## 6. 配置接口

### 6.1 获取配置

**GET** `/api/v1/config`

### 6.2 更新配置

**PUT** `/api/v1/config`

### 6.3 获取 LLM 配置

**GET** `/api/v1/config/llm`

响应：
```json
{
  "code": 0,
  "data": {
    "models": {
      "default": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "temperature": 0.7
      }
    }
  }
}
```

### 6.4 更新 LLM 配置

**PUT** `/api/v1/config/llm`

请求体：
```json
{
  "models": {
    "default": {
      "provider": "deepseek",
      "model": "deepseek-v4-flash",
      "api_key": "sk-xxx",
      "base_url": "https://api.deepseek.com/v1",
      "temperature": 0.7,
      "max_tokens": 4096
    }
  }
}
```

### 6.5 获取工作流配置

**GET** `/api/v1/config/workflow`

### 6.6 更新工作流配置

**PUT** `/api/v1/config/workflow`

### 6.7 获取统计信息

**GET** `/api/v1/config/stats`

---

## 7. 管理员接口

> 管理员接口**需登录**（Bearer Token）。

### 7.1 节点管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/nodes` | 节点管理列表 |
| POST | `/api/v1/admin/nodes` | 新增节点 |
| PUT | `/api/v1/admin/nodes/{node_id}` | 更新节点 |
| DELETE | `/api/v1/admin/nodes/{node_id}` | 删除节点 |
| POST | `/api/v1/admin/nodes/import` | 导入节点 |
| GET | `/api/v1/admin/nodes/export` | 导出节点 |
| GET | `/api/v1/admin/nodes/{node_id}/backups` | 节点备份列表 |
| POST | `/api/v1/admin/nodes/{node_id}/backups/{version}/restore` | 恢复备份 |

### 7.2 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/config` | 管理员配置 |
| PUT | `/api/v1/admin/config` | 更新管理员配置 |
| GET | `/api/v1/admin/config/llm` | LLM配置 |
| PUT | `/api/v1/admin/config/llm` | 更新LLM配置 |
| GET | `/api/v1/admin/config/workflow` | 工作流配置 |
| PUT | `/api/v1/admin/config/workflow` | 更新工作流配置 |
| GET | `/api/v1/admin/config/stats` | 统计信息 |
| POST | `/api/v1/admin/config/test-llm` | 测试LLM连接 |

### 7.3 测试 LLM 连接

**POST** `/api/v1/admin/config/test-llm`

请求体（可选，不传则用当前配置）：
```json
{
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "api_key": "sk-xxx",
  "base_url": "https://api.deepseek.com/v1"
}
```

响应：
```json
{
  "code": 0,
  "data": {
    "success": true,
    "latency_ms": 1234,
    "response_preview": "Hello, I am..."
  }
}
```

---

## 8. Webhook 接口

> Webhook 接口**需登录**。

### 8.1 列出已注册 Webhook

**GET** `/api/v1/webhooks`

响应：
```json
{
  "code": 0,
  "data": {
    "callbacks": {
      "task_xxx": {
        "url": "https://yourcompany.com/callback",
        "secret": "***",
        "events": ["task.completed", "task.failed"],
        "created_at": "2026-08-12T10:00:00"
      }
    },
    "total": 1
  }
}
```

### 8.2 获取回调历史

**GET** `/api/v1/webhooks/history?task_id=xxx&limit=20`

### 8.3 注销 Webhook

**DELETE** `/api/v1/webhooks/{task_id}`

### 8.4 测试 Webhook

**POST** `/api/v1/webhooks/{task_id}/test`

发送测试事件到回调地址，验证连通性。

---

## 9. 系统接口

### 9.1 首页/系统信息

**GET** `/`

响应：
```json
{
  "name": "Blog-Writer AI Workflow System",
  "version": "2.1.0",
  "status": "running",
  "mode": "development",
  "api_docs": "/docs",
  "api_version": "v1"
}
```

### 9.2 健康检查

**GET** `/health`

响应：
```json
{
  "status": "healthy",
  "version": "2.1.0",
  "uptime_seconds": 3600,
  "llm_provider": "configured",
  "auth_mode": "local_jwt",
  "deployment_mode": "development"
}
```

### 9.3 就绪探针

**GET** `/ready`

数据库/配置失败返回 503，LLM 仅作为能力项不影响探针。

### 9.4 指标

**GET** `/api/v1/metrics?format=json`

| 参数 | 说明 |
|------|------|
| `format=json` | JSON 格式（默认） |
| `format=prometheus` | Prometheus 格式，可直接被 Prometheus 抓取 |

### 9.5 通知渠道

**GET** `/api/v1/notifications/channels`

### 9.6 API 文档

- Swagger UI：`/docs`
- ReDoc：`/redoc`
- OpenAPI JSON：`/openapi.json`

---

## 10. 错误码

### 10.1 HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 400 | 参数错误 |
| 401 | 认证失败 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 422 | 参数验证失败 |
| 429 | 请求过于频繁（限流） |
| 500 | 服务器内部错误 |
| 503 | 服务未就绪 |

### 10.2 业务错误码（code 字段）

| code | 说明 |
|------|------|
| 0 | 成功 |
| 1001 | 参数错误 |
| 1002 | 认证失败 |
| 1003 | 权限不足 |
| 1004 | 资源不存在 |
| 1005 | 任务不存在 |
| 1006 | 任务状态不允许此操作 |
| 1007 | 节点不存在 |
| 1008 | 品牌不存在 |
| 1009 | 文件格式不支持 |
| 1010 | 文件过大 |
| 2001 | LLM 调用失败 |
| 2002 | 工作流执行失败 |
| 2003 | 节点检查未通过 |
| 3001 | Webhook 回调失败 |
| 4001 | 限流 |
| 5000 | 服务器内部错误 |

### 10.3 错误响应示例

```json
{
  "code": 1005,
  "message": "任务不存在",
  "data": null,
  "timestamp": 1691234567890
}
```

```json
{
  "code": 1009,
  "message": "文件格式不支持，仅允许 .md/.txt",
  "data": { "allowed_extensions": [".md", ".txt"] },
  "timestamp": 1691234567890
}
```

---

## 附录：完整调用流程示例

### 场景：从零启动一个写作任务并发布到 WordPress

```bash
# 1. 上传品牌资料
curl -X POST http://localhost:8000/api/brands/upload \
  -F "display_name=SMS Boosting" \
  -F "files=@brand-info.md"

# 2. 获取品牌列表，拿到 inner_path
curl http://localhost:8000/api/brands

# 3. 启动写作任务
curl -X POST http://localhost:8000/api/tasks/start \
  -H "Content-Type: application/json" \
  -d '{
    "brand_path": "./brands/sms-boosting",
    "keywords": "sms api, sms gateway",
    "mode": "auto"
  }'

# 4. 轮询任务状态
curl http://localhost:8000/api/tasks/task_20260812_100748_75321e

# 5. 查看日志
curl "http://localhost:8000/api/tasks/task_20260812_100748_75321e/logs?limit=50"

# 6. 任务完成后，查看发布记录（在实例目录下）
#    blog_writer/instance/task_xxx/发布记录.json

# 7. 如失败，从断点续跑
curl -X POST http://localhost:8000/api/tasks/task_xxx/resume-from \
  -H "Content-Type: application/json" \
  -d '{"node_file": "S007-visual.json"}'
```

---

*文档结束。配置说明详见：`docs/CONFIGURATION.md`*
