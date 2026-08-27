# Blog-Writer

> 企业级多Agent人机协同SEO博客与社媒内容自动化系统

基于多Agent架构的内容生产平台，实现从关键词输入、品牌资料理解、BID智能标识、正文写作、质量审核到WordPress发布的全流程自动化。

---

## 功能特性

- **多Agent协同**：自研ReAct风格Agent执行器，18个工作流节点分工协作
- **BID 7层标识体系**：动笔前确定文章受众、体裁、结构、语气等44个点位
- **三种运行模式**：auto全自动 / supervised关键节点审核 / manual全手动
- **并发任务调度**：支持优先级排队、动态调整并发数、暂停/恢复/断点续跑
- **品牌知识库**：多品牌资料管理，自动适配语气风格和禁用词
- **WordPress发布**：自动生成草稿，写入Rank Math SEO元数据
- **人工审核**：BID审核、正文审核、Gate审核三级质量把控
- **Webhook回调**：可订阅终态与步骤事件，HMAC-SHA256 验签；支持幂等启动与批量编排

---

## 快速开始

### 环境要求
- Python 3.12+
- LLM API Key（DeepSeek / OpenAI兼容接口）

### 3步跑通

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY、BLOG_WRITER_ADMIN_PASSWORD

# 3. 启动
python run.py
```

访问 http://localhost:8000，上传品牌资料后即可启动写作任务。

### Docker 部署

```bash
cp .env.example .env
docker compose up -d
```

---

## 文档索引

| 文档 | 说明 | 读者 |
|------|------|------|
| [docs/使用指南.md](docs/使用指南.md) | 配置说明 + 服务器部署 | 运维 |
| [docs/integration/对接指南.md](docs/integration/对接指南.md) | API接口 + 完整调用示例 + 错误码 | 开发 |
| [docs/架构流程图.md](docs/架构流程图.md) | 系统架构与工作流节点 | 架构/开发 |
| [docs/integration/openapi.json](docs/integration/openapi.json) | 完整OpenAPI规范（含 batch / Idempotency-Key） | 开发 |
| [scripts/generate_java_client.sh](scripts/generate_java_client.sh) | 从 OpenAPI 生成 Java 客户端 | 开发 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| Agent执行器 | 自研ReAct风格（类LangGraph设计） |
| 大模型 | OpenAI兼容接口（DeepSeek默认） |
| 数据库 | SQLite（开发）/ PostgreSQL / MySQL |
| 状态存储 | 内存（单进程）/ Redis（多副本） |
| 前端 | 原生HTML + JavaScript（无构建依赖） |
| 部署 | Docker / Docker Compose / Nginx |

---

## 项目结构

```
blog-writer-main/
├── blog_writer/           # 核心代码
│   ├── agent/             # Agent执行器
│   ├── api/               # REST API路由
│   ├── llm/               # LLM客户端
│   ├── nodes/             # 18个工作流节点定义（JSON）
│   ├── workflow/          # 工作流引擎与任务控制
│   ├── web/               # 前端静态文件
│   └── instance/          # 任务运行时数据（git忽略）
├── brands/                # 品牌资料
├── docs/                  # 项目文档
├── deploy/                # 部署配置（Nginx等）
├── tools/                 # 辅助脚本
├── tests/                 # 测试代码
├── .env.example           # 环境变量模板
├── config.json.example    # 应用配置模板
├── docker-compose.yml     # Docker编排
├── Dockerfile             # 容器镜像
└── requirements.txt       # Python依赖
```

---

## 工作流节点（16步主流程 + 2批量）

```
S000启动 → S001 BID推断 → [S001H审核] → S002内容PRD → S003结构
→ S004正文 → [S004H审核] → S004内容校验 → S005字段化 → S006呈现
→ S007视觉 → S008评审 → S009 Gate → [S009H审核] → S010发布包 → S011 WP发布
```

---

## 配置说明

核心配置通过 `.env` 设置，详见 [docs/使用指南.md](docs/使用指南.md)。

| 变量 | 必填 | 说明 |
|------|------|------|
| `LLM_API_KEY` | ✅ | 大模型API密钥 |
| `LLM_BASE_URL` | ✅ | 大模型接口地址 |
| `BLOG_WRITER_ADMIN_PASSWORD` | ✅ | 管理员密码 |
| `DB_BACKEND` | - | sqlite(默认) / postgres / mysql |
| `MAX_CONCURRENT_TASKS` | - | 最大并发任务数，默认5 |

---

## License

MIT
