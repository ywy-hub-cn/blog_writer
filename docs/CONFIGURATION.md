# Blog-Writer 配置指南（精简版）

> 最后更新：2026-08-12 | 详细版见 Git 历史或 `docs/API.md`

---

## 一、配置文件索引

| 文件 | 用途 | 必填 |
|------|------|------|
| `.env` | 环境变量：LLM密钥、数据库、管理员密码 | ✅ |
| `blog_writer/config.json` | 应用配置：模型、工作流参数 | 已预填，一般不改 |
| `brands/<品牌ID>/wp-config.json` | WordPress发布配置 | 发布时需要 |
| `brands/<品牌ID>/*.md` | 品牌资料文档 | ✅ |

**优先级**：环境变量 > config.json > 代码默认值
**生效方式**：改 `.env` 必须重启服务；改 `wp-config.json` 即时生效

---

## 二、快速开始（3步跑通）

### 1. 装依赖
```bash
pip install -r requirements.txt
```

### 2. 配 .env（3个必填项）
```env
LLM_API_KEY=sk-你的密钥
LLM_BASE_URL=https://api.deepseek.com/v1
BLOG_WRITER_ADMIN_PASSWORD=你的密码
```

### 3. 启动
```bash
python run.py
```
访问 http://localhost:8000，上传品牌资料后即可启动任务。

---

## 三、.env 核心配置

### 必填

| 变量 | 说明 | 示例 |
|------|------|------|
| `LLM_API_KEY` | 大模型API密钥 | `sk-xxx` |
| `LLM_BASE_URL` | 大模型地址 | `https://api.deepseek.com/v1` |
| `BLOG_WRITER_ADMIN_PASSWORD` | 管理员密码 | `admin123` |

### 常用可选

| 变量 | 默认 | 说明 |
|------|------|------|
| `DB_BACKEND` | `sqlite` | 数据库：sqlite / postgres / mysql |
| `BLOG_WRITER_STATE_BACKEND` | `memory` | 状态存储：memory / redis |
| `BLOG_WRITER_API_TOKEN` | - | API调用Token（X-API-Key头） |
| `CORS_ORIGINS` | localhost | 跨域域名，逗号分隔 |
| `COMPANY_DOMAIN` | - | 公司域名，生产环境自动加子域 |
| `RESPONSE_CASE` | `snake` | 响应字段：snake / camel（Java对接用camel） |
| `BLOG_WRITER_MODE` | `development` | 运行模式：development / production |

### 数据库（PostgreSQL 示例）
```env
DB_BACKEND=postgres
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=blog_writer
DB_USER=postgres
DB_PASSWORD=xxx
```

---

## 四、品牌资料配置

### 目录结构
```
brands/
└── sms-boosting/          # 品牌ID（中文名称自动转拼音）
    ├── brand-info.md      # 品牌介绍（必填）
    ├── products.md        # 产品信息（建议）
    ├── keywords.md        # 关键词库（建议）
    ├── forbidden.txt      # 禁用词（可选）
    └── wp-config.json     # WordPress配置（发布时需要）
```

### 上传方式
- **前端**：首页点「上传新品牌资料」，选文件上传（支持多选/文件夹）
- **API**：`POST /api/brands/upload`，字段 `display_name` + `files`
- **手动**：直接在 `brands/` 下建目录放文件，重启服务

---

## 五、WordPress 发布配置

> 不配也能跑通，最后一步自动 dry-run（模拟发布，不阻塞流程）

### 文件位置
`brands/<品牌ID>/wp-config.json`（模板见 `brands/wp-config.example.json`）

### 配置内容
```json
{
  "site_url": "https://blog.yourcompany.com",
  "username": "你的WP用户名",
  "app_password": "xxxx xxxx xxxx xxxx xxxx xxxx"
}
```

### 获取应用密码
1. WP后台 → 用户 → 个人资料 → 应用密码
2. 输入名称（如 blog-writer）→ 添加新应用密码
3. 复制生成的密码（只显示一次，不是登录密码）

### 发布行为
- 文章状态：**draft（草稿）**，不会直接发布
- 自动设置特色图像、写入Rank Math SEO标题/描述
- 前置条件：WP 5.6+、REST API启用

---

## 六、工作流模式

| 模式 | 说明 | 人工审核 |
|------|------|----------|
| `auto` | 全自动（默认） | 无 |
| `supervised` | 监督模式 | BID审核 + 正文审核 |
| `manual` | 手动模式 | 全部审核 + 每步确认 |

启动任务时通过 `mode` 参数指定。

---

## 七、配置检查清单

### 本地跑通（最小）
- [ ] `.env` 中 `LLM_API_KEY` 已填
- [ ] `pip install -r requirements.txt` 成功
- [ ] 至少上传1个品牌资料
- [ ] `python run.py` 启动无报错
- [ ] 访问 `/health` 返回 healthy

### 生产环境
- [ ] `BLOG_WRITER_MODE=production`
- [ ] 数据库切换为 PostgreSQL/MySQL
- [ ] 管理员密码改为强密码
- [ ] `CORS_ORIGINS` 配置实际域名
- [ ] 每个品牌有 `wp-config.json`
- [ ] HTTPS 已配置

---

## 八、常见问题

**Q: 改 .env 不生效？**
A: 必须重启服务。uvicorn --reload 只监听代码文件，不重新加载 .env。

**Q: 任务卡住？**
A: 看日志 `GET /api/tasks/{task_id}/logs`，或从断点续跑 `POST /api/tasks/{task_id}/resume-from`。

**Q: WP发布失败？**
A: 检查 `wp-config.json` 是否在品牌目录下、app_password 是否正确（是应用密码不是登录密码）。

---

*接口文档见 `docs/API.md`*
