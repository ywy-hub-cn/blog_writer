# blog-writer Method 架构说明书

> 最后更新：2026-08-04  
> AI化优化版：支持三种运行模式、人工审核节点、风险分级路由、批量任务调度
>
> **Python 运行时对齐（2026-08-04）**  
> - `registry.json` → `routing` 已由 `blog_writer.workflow.routing.WorkflowRouter` 执行（含 `on_pass`/`on_fail`/`mode_override`/`risk_based`）  
> - 失败策略：重试耗尽后 fail-closed（任务 `failed`），或按 `on_fail` 回跳重写  
> - S008/S009：节点 `resources.isolated_session=true`，`AgentExecutor` 启用隔离会话（全新消息、不预读产物）  
> - 发布：`tools/blog-writer/assemble_publish.py`、`publish_to_wp.py`  
> - 平台对接与环境变量见 `docs/integration/对接指南.md`  
>
> 下文中的 `sessions_spawn` 等表述保留 method-skill 语义；FastAPI 服务以隔离 `AgentExecutor` 等价实现。

---

## 一、概述

blog-writer 是运行在 method-like-skill 框架下的一个**通用自由模式博客写作方法**，现已升级为**社媒运营AI工作流**。

**核心理念：**
- 品牌无关 — 品牌文件通过 `brand_path` 参数传入，文件名随意
- BID 驱动 — 7 层 44 点位的分类标识系统，动笔前确定每篇文章的精确走向
- 隔离自审 — 每步评审 spawn 独立 session，不继承对话上下文
- 结构化输出 — 最终 HTML 全文带 Schema 语义标记
- **可控可复用** — 支持三种运行模式，关键节点人工审核
- **风险分级** — 基于 BID RK 字段自动选择发布路径
- **批量执行** — 支持多关键词并行生成，任务状态跟踪

---

## 二、整体流程

```
用户 (depth 0)
│
├─ spawn 调度 session (depth 1, timeout=600s, 参见 registry.json default_timeout)
│
│  S000 启动初始化
│  │  输入: brand_path, keywords, user_note, brand_site_url, mode
│  │  动作: 校验 brand_path → 复制文件 → 扫描文件名推断角色 → 写manifest
│  │  产出: 001 启动确认.md + brand/manifest.json
│  │  校验: 关键词非空 / manifest存在 / 至少1个.md文件
│  │  路由: 通过→S001, 失败→S000(重试2次)
│  │
│  ▼
│  S001 BID自动推断
│  │  输入: 001 启动确认.md + references/bid-system.md + references/bid-rules.md
│  │  动作: 读品牌文件 → web_search了解SERP →
│  │        推断CO/WB/SE/GE/CL/LO/ST七层44点位 →
│  │        逐条校验P0硬约束 → 写入
│  │  产出: 000 BID.json
│  │  校验: BID存在 / P0全部通过 / 7层均非空
│  │  路由: 通过→S001H(非auto模式), 通过→S002(auto模式), 失败→S001(重试3次)
│  │
│  ▼ (supervised/manual模式)
│  S001H BID人工审核
│  │  输入: 000 BID.json + 001 启动确认.md
│  │  动作: 展示BID摘要、标题、关键词、风险等级 →
│  │        等待人工决策（通过/修改关键词/修改标题/修改提示词/重新推断）
│  │  产出: 审核日志 + 更新后的BID
│  │  校验: 审核日志存在 / BID validation.passed=true
│  │  路由: 通过→S002, 驳回→S001(重新推断)
│  │
│  ▼
│  S002 内容方案
│  │  输入: 001 启动确认.md + brand/manifest.json
│  │  动作: 读manifest按角色取品牌文件 →
│  │        web_search了解SERP →
│  │        BID的ST决定结构模板、CT决定体裁、GC决定范围 →
│  │        写方案(选题/结构/H2-H3/SEO/CTA/边界)
│  │  产出: 002 内容方案.md
│  │  校验: H2≥4且有semantic_type / title≤70字符 / 主关键词非空
│  │  路由: 通过→S003, 失败→S002(重试3次)
│  │
│  ▼
│  S003 自审方案
│  │  输入: 002 内容方案.md
│  │  动作: 构建评审prompt →
│  │        sessions_spawn(context=isolated, mode=run) →
│  │        sessions_yield等待 → 读评审结果 →
│  │        exec write_step_output.py 写入独立文件
│  │  产出: 008 自审结果.md（独立文件，不追加到正文）
│  │  校验: passed=true / score≥3 / 存在##自审结果节
│  │  路由: 通过→S004, 失败→S002改方案(重试3次)
│  │
│  ▼
│  S004 正文写作
│  │  输入: 002 内容PRD.md + 003 文章结构.md + brand/manifest.json
│  │  动作: 读 manifest 按角色取品牌文件 →
│  │        BID 的 TN 决定语气、DP 决定深度字数、PR 决定受众角度 →
│  │        web_search 收集事实支撑 →
│  │        写完整正文（H2-H3/段落/列表/表格/FAQ/Conclusion/References）
│  │  产出: 004 正文.md
│  │  校验: 无H1 / H2≥4 / title与方案一致 / Body节存在
│  │  路由: 通过→S004H(非auto模式), 通过→S004-content-validate(auto模式), 失败→S004(重试3次)
│  │
│  ▼ (supervised/manual模式)
│  S004H 正文人工审核
│  │  输入: 004 正文.md + 008 自审结果.md + 000 BID.json + 003 文章结构.md
│  │  动作: 展示正文预览、自审评分、风险等级、合规检查结果 →
│  │        等待人工决策（通过/修改内容/修改标题/修改提示词/重新写作/修改结构）
│  │  产出: 审核日志 + 更新后的正文/BID
│  │  校验: 审核日志存在 / 正文非空
│  │  路由: 通过→S004-content-validate, 驳回→S004(重新写作)
│  │
│  ▼
│  S004-content-validate 内容质量校验
│  │  输入: 004 正文.md
│  │  动作: 执行内容质量校验脚本
│  │  产出: 校验结果
│  │  路由: 通过→S005, 失败→S004(重试2次)
│  │
│  ▼
│  S005 字段化
│  │  输入: 004 正文.md + 003 文章结构.md + 002 内容PRD.md + 000 BID.json
│  │  动作: 逐段打 data-field + data-seq 标记 →
│  │        每个 <section> 标记 semantic_type →
│  │        段落级标记（hook/data/quote/explanation/example/comparison 等）
│  │  产出: 005 字段化文档.html
│  │  校验: 存在非空 / 每 <section> 有 data-field / 每 <p> 有 data-field
│  │  路由: 通过→S006, 失败→S005(重试3次)
│  │
│  ▼
│  S006 呈现文档
│  │  输入: 005 字段化文档.html + 000 BID.json + 002 内容PRD.md
│  │  动作: 读 BID 取 title/slug/meta → 读 html-rules 取 CSS 样式 →
│  │        包裹完整独立 HTML 页面（head/style/SEO meta/OG/Twitter Card）
│  │  产出: 006 呈现文档.html
│  │  校验: 存在非空 / 含 !DOCTYPE html / 含 data-field 属性
│  │  路由: 通过→S007, 失败→S006(重试2次)
│  │
│  ▼
│  S007 视觉素材生产
│  │  输入: 006 呈现文档.html + 000 BID.json
│  │  动作: 提取 H2 列表 → 判断 Mermaid 或图片配图 →
│  │        生成 Mermaid 代码 / Unsplash 搜图 →
│  │        注入 Mermaid CDN + 初始化脚本到 <head> →
│  │        在对应 <section> 内插入视觉元素 HTML →
│  │        封面图插入 <div class="blog-content"> 开头
│  │  产出: 006 呈现文档.html（含视觉元素）
│  │  校验: 存在非空 / 至少包含 figure 或 visual-mermaid 标签
│  │  路由: 通过→S008, 失败→S007(重试2次)
│  │
│  ▼
│  S008 自审正文+打分
│  │  输入: 005 字段化文档.html + 004 正文.md + 003 文章结构.md
│  │  动作: 读评分规则 + 反模板化 + 可信度 + 深度增强 + 引用规则 →
│  │        构建评审 prompt →
│  │        sessions_spawn(context=isolated, mode=run) →
│  │        sessions_yield 等待 → 读 JSON 结果 →
│  │        exec write_step_output.py 写入 008 自审结果.md
│  │  产出: 008 自审结果.md（独立文件，不追加到正文）
│  │  校验: passed=true / 任一维度≥3 / 存在 ##自审结果节 / 引用可核验URL
│  │  路由: 通过→S009, 失败→S004 改正文(重试3次)
│  │
│  ▼
│  S009 Gate校验
│  │  输入: 006 呈现文档.html + 005 字段化文档.html + 004 正文.md
│  │  动作: 构建 Gate prompt（首屏/结构/质量/SEO/格式洁净度/参考文献）→
│  │        sessions_spawn(context=isolated, mode=run) →
│  │        sessions_yield 等待 → 读 JSON 结果 →
│  │        exec write_step_output.py 写入 009 Gate结果.md
│  │        禁用词检测（exec脚本）→ URL真实性验证（exec脚本）→ 品牌合规检查
│  │  产出: 009 Gate结果.md（独立文件，不追加到正文）
│  │  校验: passed=true / 存在 ##Gate 结果节
│  │  路由: 通过→S009H(非auto模式或高风险), 通过→S010(auto模式且低风险), 失败→S004(重试2次)
│  │
│  ▼ (supervised/manual模式或RK≥03)
│  S009H Gate人工审批
│  │  输入: 009 Gate结果.md + 006 呈现文档.html + 004 正文.md + 000 BID.json + 008 自审结果.md
│  │  动作: 展示Gate校验结果、风险等级、合规检查、AI自审评分 →
│  │        根据RK风险等级执行单级/多级审批 →
│  │        等待人工决策（通过发布/修改内容/修改标题/重新审核/驳回）
│  │  产出: 审批日志 + 更新后的内容/BID
│  │  校验: 审批日志存在 / 高风险内容(RK≥04)必须有人工审批记录
│  │  路由: 通过→S010, 驳回→S004(改正文)或终止任务
│  │
│  ▼
│  S010 发布包
│  │  输入: 001 启动确认 + 002 内容PRD + 006 呈现文档.html + 000 BID.json
│  │  动作1: 读 brand_site_url → web_fetch 爬官网找内链 →
│  │         根据 BID 的 PI/TH 筛选同主题文章 2-4 篇 →
│  │         写入 002 的 ##内链候选 节
│  │  动作2: 提取 keyword/title/slug/meta → 嵌入内链 →
│  │         从 006 提取正文 HTML →
│  │         构建 article 壳 + SEO meta + data-bid →
│  │         计算 Meta 描述 ≤160 字符 → 写入 007 发布包
│  │  产出: 007 发布包.md
│  │  校验: Keyword 代码框非空 / HTML 代码框非空 /
│  │         含 data-field 属性 / 含 <section> 标签 /
│  │         Meta≤160 字符 / 不含 JSON-LD
│  │  路由: 通过→S011, 失败→S010(重试1次)
│  │
│  ▼
│  S011 WordPress发布
│  │  输入: 007 发布包.md
│  │  动作: 通过WordPress API发布文章
│  │  产出: 发布结果
│  │  路由: 通过→完成, 失败→S011(重试2次)
│  │
│  ▼
│  完成
```

---

## 三、运行模式设计

### 3.1 三种运行模式

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| `auto` | 全自动模式，无人干预，跳过所有人工审核节点 | 低风险、标准化内容（RK≤02） |
| `supervised` | 监督模式，关键节点人工审核（S001H、S004H），高风险内容强制Gate审批（S009H） | 中等风险、需要质量把控（RK=03） |
| `manual` | 手动模式，每步人工确认，所有审核节点强制通过 | 高风险、敏感内容（RK≥04） |

### 3.2 模式切换机制

在 `registry.json` 中通过 `mode_config` 配置不同模式的路由规则：

```json
{
  "mode_config": {
    "auto": {
      "skip_review": ["S001H-human-review-bid.json", "S004H-human-review-draft.json", "S009H-human-review-gate.json"]
    },
    "supervised": {
      "required_review": ["S001H-human-review-bid.json", "S004H-human-review-draft.json"],
      "conditional_review": {"S009H-human-review-gate.json": "risk_level >= 03"}
    },
    "manual": {
      "required_review": ["S001H-human-review-bid.json", "S004H-human-review-draft.json", "S009H-human-review-gate.json"],
      "step_confirmation": true
    }
  }
}
```

---

## 四、风险分级策略

### 4.1 风险等级定义（基于 BID RK 字段）

| RK值 | 风险等级 | 描述 | 处理策略 |
|------|---------|------|----------|
| 01 | 低风险 | 通用知识、教育内容 | 全自动发布 |
| 02 | 中低风险 | 产品介绍、使用指南 | 自动发布 + 事后审核 |
| 03 | 中风险 | 对比评测、行业分析 | 人工审核后发布 |
| 04 | 中高风险 | 技术指南、实操教程 | 强制人工审批（多级） |
| 05 | 高风险 | 敏感话题、争议内容 | 多级审批 + 法务审核 |

### 4.2 风险路由逻辑

```
S009 Gate校验完成
    │
    ├─ RK ≤ 02 → S010 发布包（全自动）
    │
    ├─ RK = 03 → S009H 人工审批（单级）
    │              │
    │              └─ 通过 → S010
    │
    └─ RK ≥ 04 → S009H 人工审批（多级）
                   │
                   ├─ 一级审批 → 二级审批
                   │              │
                   │              └─ 通过 → S010
                   │
                   └─ 驳回 → S004 改正文
```

### 4.3 合规检查机制

Gate 校验阶段执行以下系统自检：

| 检查项 | 方式 | 失败处理 |
|--------|------|----------|
| 禁用词检测 | exec Python脚本 | 标记为不通过，列出命中词 |
| URL真实性验证 | exec Python脚本（HEAD请求） | 标记为不通过，列出不可访问URL |
| 品牌合规 | LLM对照品牌知识库 | 标记为不通过，列出违规点 |
| 格式洁净度 | LLM检查 | 标记为不通过，列出格式问题 |

---

## 五、BID 驱动映射

BID 的 7 层 44 点位并非所有步骤都用到。以下是每步从 BID 读取的核心字段：

| 步骤 | 读 BID 字段 | 影响 |
|------|------------|------|
| S002 方案 | `st`（模板）, `ct`（体裁）, `gc`（范围）, `si`（意图） | 决定方案用什么模板写、覆盖多宽 |
| S004 正文 | `tn`（语气）, `dp`（深度→字数）, `pr`（受众）, `al`（水平）, `so`（原创度） | 文字风格、篇幅、技术深度 |
| S005 字段化 | `st`（模板） | data-field 类型标注 |
| S006 呈现文档 | `st`（模板） | 确定呈现样式 |
| S007 视觉素材 | `st`（模板） | 决定视觉风格（Mermaid/图片） |
| S008 自审 | `so`（原创度） | 检查原创要求是否达标 |
| S009 Gate | `rk`（风险水平） | 高风险审更严，决定是否强制人工审批 |
| S010 发布包 | `pi`, `th`（主题域） | 找内链时定位同主题文章 |
| S010 发布包 | 全部 BID | 写入 data-bid 属性和元信息 |

**BID 各层含义速查：**
```
CO(14): AT资产类型 TH主题Hub PI支柱 CT体裁 PV目的 PR受众 AL水平
        DP深度 TM时效 FM渠道 TN语气 SO原创度 EV证据类型
WB(7):  OBJ业务目标 UC使用场景 JS旅程 CTA方式 CI强度 PM产品 RK风险
SE(7):  SI搜索意图 QS查询形态 KL关键词层次 KC关键词类型
        SF SERP特性 SC Schema IC索引策略
GE(5):  GI AI角色 GS信号 GF结构化 GN外部锚定 GC边界
CL(6):  PI支柱 SUB子集群 CR集群角色 IL内链职责 LT外链 PF程序化
LO(1):  语言/市场
ST(6):  01步骤指南 02清单列表 03概念定义 04对比评测 05研究报告 06完整指南
```

---

## 六、路由与状态机

> **已落地**：`WorkflowService` 通过 `WorkflowRouter` 读取下表对应的 `registry.json` → `routing`；回跳会清除目标节点及之后的完成态。重试/回跳预算耗尽则任务 `failed`（fail-closed）。

### 6.1 路由表（supervised模式）

| 步骤 | on_pass | on_fail | max_retries | 备注 |
|------|---------|---------|-------------|------|
| S000 startup | S001 bid | S000 startup | 2 | |
| S001 bid | S001H human_review_bid | S001 bid | 3 | BID审核 |
| S001H human_review_bid | S002 prd | S001 bid | 0 | 人工确认后继续 |
| S002 prd | S003 structure | S002 prd | 3 | |
| S003 structure | S004 draft | S003 structure | 3 | |
| S004 draft | S004H human_review_draft | S004 draft | 3 | 正文审核 |
| S004H human_review_draft | S004-content-validate | S004 draft | 0 | 人工确认后继续 |
| S004-content-validate | S005 field | S004 draft | 2 | |
| S005 field | S006 preview | S005 field | 3 | |
| S006 preview | S007 visual | S006 preview | 2 | |
| S007 visual | S008 review_draft | S007 visual | 2 | |
| S008 review_draft | S009 gate | S004 draft(改正文) | 3 | |
| S009 gate | S009H human_review_gate | S004 draft(改正文) | 2 | Gate审批 |
| S009H human_review_gate | S010 publish | S004 draft(改正文) | 0 | 人工审批后继续 |
| S010 publish | S011 publish_wp | S010 publish | 1 | |
| S011 publish_wp | 完成 | S011 publish_wp | 2 | |

### 6.2 模式覆盖路由

- **auto模式**: S001→S002, S004→S004-content-validate, S009→S010（跳过所有人工审核节点）
- **风险分级**: RK≤02时S009直接→S010，RK≥03时必须经过S009H

### 6.3 关键路由逻辑

- **S008 自审正文不通过 → 回 S004 改正文**
- **S009 Gate 不通过 → 回 S004 改正文**
- **S001H/S004H/S009H 驳回 → 回对应步骤重新执行**
- **重试耗尽 → 标记为 failed，调度 session 回复错误 JSON**
- 步进 session 返回 `status=failed` 时不消耗重试次数，直接再跑一次
- 步进 session 返回 `status=error`（超时/崩溃）时消耗一次重试次数

---

## 七、人工审核节点

### 7.1 S001H BID人工审核

**作用**: BID推断后的人工审核，支持关键词、标题、提示词调整

**操作选项**:
1. ✓ 通过 — 确认BID，直接进入内容PRD阶段
2. ✏ 修改关键词 — 重新输入关键词，重跑BID推断
3. ✏ 修改标题 — 调整文章标题和SEO标题
4. ✏ 修改提示词 — 更新user_note写作要求
5. 🔄 重新推断 — 重新执行BID推断

**产出**: 001H 审核日志.md

### 7.2 S004H 正文人工审核

**作用**: 正文写作后的人工审核，支持内容修改和结构调整

**操作选项**:
1. ✓ 通过 — 确认正文，直接进入字段化阶段
2. ✏ 修改内容 — 编辑正文内容，重跑正文写作
3. ✏ 修改标题 — 调整文章标题和SEO标题
4. ✏ 修改提示词 — 更新user_note写作要求
5. 🔄 重新写作 — 重新执行正文写作
6. 📋 修改结构 — 调整文章结构大纲

**产出**: 004H 审核日志.md

### 7.3 S009H Gate人工审批

**作用**: Gate校验后的人工审批，基于风险等级执行单级/多级审批

**操作选项**:
1. ✓ 通过发布 — 确认文章，进入发布包阶段
2. ✏ 修改内容 — 编辑正文，重跑正文写作
3. ✏ 修改标题 — 调整文章标题和SEO标题
4. 🔄 重新审核 — 返回自审阶段
5. ❌ 驳回 — 终止任务

**产出**: 009H 审批日志.md

---

## 八、品牌文件系统

### 用户需要做的事

1. 在某个目录下放 `.md` 文件（命名随意）
2. spawn 时传 `brand_path` 指向这个目录

### S000 自动做的事

1. 复制 `brand_path/*.md` 到实例的 `brand/` 目录
2. 扫描每个文件名，按以下优先级匹配关键词，推断角色：

```
关键词匹配规则（从上到下，匹配到即停止）：

  含【禁用词|forbidden|红线|黑名单|禁止】    → 禁用词
  含【语气|调性|tone|voice|style】          → 语气调性
  含【受众|画像|audience|persona】          → 受众画像
  含【评审|review|标准|criterion】          → 评审标准
  含【调用|usage|使用规则】                  → 知识库规则
  含【品牌知识|知识库|knowledg】             → 品牌知识
  含【模板|template|规范|SEO|颜色|asset】    → 其他（内容参考）
  未匹配                                    → 其他
```

3. 写入 `brand/manifest.json`:

```json
{
  "files": [
    {"name": "SMS Boosting品牌知识库.md", "path": "brand/SMS Boosting品牌知识库.md", "inferred_role": "品牌知识"},
    {"name": "SMS Boosting语气调性指南.md", "path": "brand/SMS Boosting语气调性指南.md", "inferred_role": "语气调性"}
  ],
  "has_brand_knowledge": true,
  "has_tone_guidelines": true,
  "has_forbidden_words": false,
  "has_audience_profile": true,
  "has_review_criteria": false
}
```

4. S002/S004 读 manifest → 按角色读对应文件 → 不存在的跳过

### 最少要求

- **至少 1 个 `.md` 文件**（否则 S000 的 check 直接 hard_fail）
- 推荐至少放品牌知识库和语气调性

---

## 九、隔离评审机制

S008（自审正文+打分）/ S009（Gate 校验）两步使用独立 session 做评审。

> **FastAPI 实现**：节点 JSON 设置 `resources.isolated_session: true`；`AgentExecutor` 每次执行清空消息历史，系统提示声明隔离评审，文件列表仅列名不预读内容。method 语义下的 `sessions_spawn(context=isolated)` 与此对应。

### 流程

```
当前步 agent (depth 2)
│
├─ 读产物文件(如 002 内容方案.md)
├─ 构建评审 prompt（含待审内容 + 评审维度 + 回复格式要求）
│
├─ sessions_spawn(context="isolated", mode="run")
│  └─ 评审 session (depth 3)
│     ├─ 只读 prompt 中的内容（不继承任何对话上下文）
│     ├─ 执行评审
│     └─ 回复纯文本 JSON
│
├─ sessions_yield → 等待评审 session 完成
├─ 解析 JSON 结果（passed / scores / issues）
├─ exec write_step_output.py 写入独立产出文件（不追加到正文，LLM 无权选择写入路径）
│
└─ checks 校验: passed=true → 通过
                 passed=false → 路由回上一步改内容
```

### 评审 session 的隔离性

- `context="isolated"` → 不继承 spawn 方的对话历史
- 评审 session 只读 workdir 中指定的产物文件
- 回复格式限定为 JSON，便于程序化处理

---

## 十、批量调度

### 10.1 批量初始化 (S-BATCH-001)

**作用**: 解析批量配置文件，并行启动多个任务实例

**输入**: batch-config.json

**工作流**:
1. 解析批量配置（batch_id、品牌路径、任务列表）
2. 验证配置完整性
3. 创建 batch-status.json 跟踪状态
4. 按 max_parallel 限制并行 spawn 实例

### 10.2 批量结果汇总 (S-BATCH-002)

**作用**: 收集所有任务状态，生成汇总报告

**工作流**:
1. 扫描所有实例目录
2. 更新 batch-status.json
3. 生成批量任务汇总报告（batch-report-{batch_id}.md）
4. 统计成功/失败/待审核数量

### 10.3 batch-config.json 模板

```json
{
  "batch_id": "batch-20260728-001",
  "name": "社媒运营系列文章",
  "mode": "supervised",
  "brand_path": "/path/to/brands/sms-boosting/",
  "brand_site_url": "https://smsboosting.com",
  "max_parallel": 3,
  "auto_retry": true,
  "tasks": [
    {
      "task_id": "task-001",
      "keywords": "SMS marketing API integration",
      "user_note": "技术受众，突出API易用性",
      "priority": "high"
    }
  ]
}
```

---

## 十一、最终 HTML 结构

S007 生成的 `Final article body` 包含完整的 Schema.org 语义标记。

### 完整结构示例

```html
<article itemscope itemtype="https://schema.org/Article">

  <meta itemprop="headline" content="文章标题">
  <meta itemprop="description" content="Meta description">
  <meta itemprop="mainEntityOfPage" content="https://example.com/blog/slug/">

  <div class="blog-content" data-bid="CO(02,01,0101,01,01,01,02,02,03,01,02,02,01,03)-WB(03,03,03,01,03,01,02)-SE(04,04,02,03,01,05,01)-GE(03,03,04,01,03)-CL(0101,00,02,01,01,01)-LO(01)-ST(04)">

    <!-- 每个 H2 区块 -->
    <section id="sec-01" itemprop="articleBody"
             itemscope itemtype="https://schema.org/ArticleSection">
      <h2 id="h2-01" itemprop="name">Section Title</h2>

      <!-- 普通段落 -->
      <p itemprop="text">Paragraph text...</p>

      <!-- 含数据/主张的关键段落 -->
      <p itemprop="text" data-claim="true">Key claim with data...</p>

      <!-- 含引用的段落 -->
      <p itemprop="text">
        <cite>Source Name</cite>
        Quoted content...
      </p>

      <!-- H3 子标题 -->
      <h3 itemprop="name">Subsection Title</h3>

      <!-- 列表 -->
      <ul itemprop="text">
        <li>Item one</li>
        <li>Item two</li>
      </ul>

      <!-- 表格 -->
      <table itemprop="text">
        <thead>
          <tr>
            <th scope="col">Column A</th>
            <th scope="col">Column B</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Value 1</td>
            <td>Value 2</td>
          </tr>
        </tbody>
      </table>

      <!-- 图片 -->
      <figure itemprop="image" itemscope itemtype="https://schema.org/ImageObject">
        <img src="image.png" alt="Description" itemprop="contentUrl">
        <figcaption itemprop="caption">Caption text</figcaption>
      </figure>
    </section>

    <!-- FAQ 区域 -->
    <section id="faq" itemscope itemtype="https://schema.org/FAQPage">
      <h2>Frequently Asked Questions</h2>

      <div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
        <h3 itemprop="name">Question text?</h3>
        <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
          <p itemprop="text">Answer text...</p>
        </div>
      </div>
    </section>

  </div>

  <!-- JSON-LD -->
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "文章标题",
    "description": "Meta description",
    "mainEntityOfPage": {"@type": "WebPage", "@id": "https://example.com/blog/slug/"},
    "hasPart": [
      {"@type": "ArticleSection", "name": "Section 1", "url": "https://example.com/blog/slug/#sec-01"},
      {"@type": "ArticleSection", "name": "Section 2", "url": "https://example.com/blog/slug/#sec-02"}
    ]
  }
  </script>

</article>
```

### 每个元素对应的 Schema

| HTML 元素 | Schema 标记 |
|-----------|-------------|
| `<article>` | `itemscope itemtype="Article"` |
| `<section>` (H2 区块) | `itemprop="articleBody" itemscope itemtype="ArticleSection"` |
| `<h2>` | `itemprop="name"` |
| `<h3>` | `itemprop="name"` |
| `<p>` | `itemprop="text"` |
| `<p data-claim="true">` | 含数据/主张的关键标记点 |
| `<cite>` | 引用来源标记 |
| `<ul>/<ol>` | `itemprop="text"` |
| `<table>` | `itemprop="text"` |
| `<figure>` | `itemprop="image" itemscope itemtype="ImageObject"` |
| `<section id="faq">` | `itemscope itemtype="FAQPage"` |
| `.mainEntity` | `itemscope itemtype="Question"` |
| `.acceptedAnswer` | `itemscope itemtype="Answer"` |
| JSON-LD | `Article + hasPart[] + FAQPage` |

---

## 十二、文件清单

### 方法母版

```
methods/blog-writer/
├── registry.json                                    路由定义（16步+批量配置）
├── batch-config.json                                批量任务配置模板
├── nodes/
│   ├── S000-startup.json        seq=0   品牌初始化+manifest
│   ├── S001-bid-infer.json      seq=1   BID自动推断+P0校验
│   ├── S001H-human-review-bid.json seq=1.5 BID人工审核
│   ├── S002-content-prd.json    seq=2   BID驱动内容PRD
│   ├── S003-structure.json      seq=3   BID驱动文章结构
│   ├── S004-draft.json          seq=4   BID驱动正文写作
│   ├── S004H-human-review-draft.json seq=4.5 正文人工审核
│   ├── S004-content-validate.json seq=4.7 内容质量校验
│   ├── S005-field.json          seq=5   data-field 标记
│   ├── S006-preview.json        seq=6   完整HTML页面
│   ├── S007-visual.json         seq=7   Mermaid/图片配图
│   ├── S008-review-draft.json   seq=8   隔离评审正文+打分
│   ├── S009-gate.json           seq=9   隔离Gate校验+合规检查
│   ├── S009H-human-review-gate.json seq=9.5 Gate人工审批
│   ├── S010-publish.json        seq=10  内链+结构化HTML
│   ├── S011-publish-wp.json     seq=11  WordPress发布
│   ├── S-BATCH-001-batch-init.json seq=-1 批量任务初始化
│   └── S-BATCH-002-batch-collect.json seq=12 批量结果汇总
└── references/
    ├── bid-system.md                                  BID体系参考
    ├── bid-rules.md                                   P0硬约束
    ├── brand-template.md                              品牌文件模板
    ├── anti-template.md                               反模板化写作规则
    ├── credibility.md                                 可信度增强规则
    ├── depth.md                                       深度增强规则
    ├── writer-rules.md                                正文写作通用约束
    ├── citation-rules.md                              引用规则与数字使用规范
    ├── seo-quality.md                                 SEO写作质量规则
    └── html-rules.md                                  HTML输出规范
```

### 品牌目录

```
brands/
├── README.md
└── sms-boosting/
    ├── SMS Boosting品牌知识库.md
    ├── SMS Boosting语气调性指南.md
    ├── SMS Boosting禁用词清单.md
    ├── SMS Boosting受众画像.md
    ├── SMS Boosting评审标准.md
    ├── SMS Boosting知识库调用规则.md
    ├── SMS Boosting博客模板规范.md
    ├── SMS BoostingSEO文章要求.md
    └── SMS Boosting品牌颜色.md
```

### 运行实例目录

```
instance/{method}-{YYYYMMDD-HHmmss}/
├── 000 BID.json                    BID 7层标识+P0校验
├── 001 启动确认.md                  启动信息+关键词+品牌官网
├── 001H 审核日志.md                 BID审核日志
├── 002 内容PRD.md                  BID驱动内容PRD
├── 003 文章结构.md                  文章H2/H3结构+semantic_type
├── 004 正文.md                     正文+自审结果+Gate结果
├── 004H 审核日志.md                 正文审核日志
├── 005 字段化文档.html              带 data-field 标记的结构化HTML
├── 006 呈现文档.html                完整HTML页面（含Mermaid/图片）
├── 007 发布包.md                    Keyword/Title/Slug/Meta/HTML
├── 008 自审结果.md                  AI自审评分结果
├── 009 Gate结果.md                  Gate校验结果
├── 009H 审批日志.md                 Gate审批日志
├── brand/                          品牌文件副本
│   ├── manifest.json               品牌文件清单
│   └── *.md                        品牌文件
└── .method/                        调度session系统文件
    ├── registry.json               方法定义副本
    └── nodes/                      节点定义副本
```

---

## 十三、参数与调用方式

### 13.1 depth 0 spawn task 模板（单任务）

```
## 参数
- instance_root: /home/skylar/.openclaw/workspace-rafayel/instance
- method_path: methods/blog-writer
- default_model: deepseek/deepseek-v4-flash
- step_timeout: 600
- brand_path: /home/skylar/.openclaw/workspace-rafayel/brands/sms-boosting/
- brand_site_url: https://smsboosting.com
- keywords: "SMS marketing API, bulk SMS"
- user_note: "偏向技术受众，突出API集成易用性"
- mode: "supervised"

## 用户需求
写一篇关于 SMS marketing API 的博客文章

## 指令
读 /home/skylar/.openclaw/workspace-rafayel/skills/method-like-skill/SKILL.md 第 4 节「调度 session」，按它执行。
```

### 13.2 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `instance_root` | ✅ | 实例根目录 |
| `method_path` | ✅ | 方法母版路径 |
| `default_model` | ✅ | 默认模型 |
| `step_timeout` / `workflow.step_timeout_minutes` | ✅ | 每步超时；运行时配置为**分钟**（`asyncio.wait_for`，clamp 30s～2h） |
| `brand_path` | ✅ | 品牌目录路径 |
| `brand_site_url` | ❌ | 品牌官网（用于内链抓取） |
| `keywords` | ✅ | 写作关键词 |
| `user_note` | ❌ | 用户附加要求 |
| `mode` | ❌ | 运行模式：auto/supervised/manual，默认auto |

### 13.3 批量任务调用

```
## 参数
- instance_root: /home/skylar/.openclaw/workspace-rafayel/instance
- method_path: methods/blog-writer
- batch_config_path: batch-config.json

## 用户需求
批量生成社媒运营系列文章

## 指令
执行 S-BATCH-001-batch-init.json 初始化批量任务
```

---

## 十四、扩展方向

| 扩展 | 方式 |
|------|------|
| **规划模式** | 新增 S001.5 步骤，S000 判断 mode="planned" 后路由到不同方案生成逻辑 |
| **跨 Agent 评审** | S003/S005 改为 sessions_send 到 Content Review Agent |
| **多语言写作** | 基于 LO 字段扩展，支持中文、西班牙语等多语言输出 |
| **社交媒体发布** | 新增节点支持微信公众号、微博、LinkedIn 等平台发布 |
| **数据分析模块** | 新增阅读量、转化率追踪分析功能 |
| **A/B 测试** | 支持不同标题/内容版本对比测试 |
| **智能选题建议** | 基于历史数据和热点自动推荐选题 |
