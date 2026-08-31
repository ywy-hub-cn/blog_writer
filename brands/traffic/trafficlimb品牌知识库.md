# TraffiClimb · 品牌知识库

> 来源：`TC-品牌知识库/`（8 个 Phase） | 汇总日期：2026-06-26
> 从市场到业务内容到对外声调，逐层映射。可执行，可维护。

**品牌官网**：https://trafficlimb.com/

---

## 目录

- [一、总体架构](#一总体架构)
- [二、全量关系索引](#二全量关系索引)
- [三、构建计划（已归档）](#三构建计划已归档)
- [四、Phase 00 — 基础档案](#四phase-00--基础档案)
- [五、Phase 01 — 市场定位](#五phase-01--市场定位)
- [六、Phase 02 — 价值观与人格](#六phase-02--价值观与人格)
- [七、Phase 03 — 声调与语言体系](#七phase-03--声调与语言体系)
- [八、Phase 04 — 视觉体系](#八phase-04--视觉体系)
- [九、Phase 05 — 内容模板](#九phase-05--内容模板)
- [十、Phase 06 / 07 — 待建设](#十phase-06--07--待建设)

---

## 一、总体架构

### 映射链路

```
01 市场定位 ──→ 02 价值观人格 ──→ 03 声调语言 ──→ 04 视觉体系
                                                     ──→ 05 内容模板
                                                     ──→ 06 表述边界
                                                                  └──→ 07 整合输出
```

每一条内容都能沿这条链路回溯到源头。Phase 是分类架不是施工顺序——先做哪块随意，产出后打标归入对应 Phase。

### Phase 定义

| Phase | 目录 | 归属 | 典型内容 |
|-------|------|------|----------|
| 00 | 基础档案 | 品牌基本信息 | 品牌定义、业务理解 |
| 01 | 市场定位 | 市场与竞争分析 | 竞品分析、目标人群、品牌定位句 |
| 02 | 价值观人格 | 品牌内核定义 | 核心价值观、人格模型、品牌-用户关系 |
| 03 | 声调语言 | 表达规范 | 声调三轴、关键词汇、禁用词、语言准则 |
| 04 | 视觉体系 | 视觉呈现 | 色彩、字体、构图、Logo、网站主题 |
| 05 | 内容模板 | 执行框架 | 各触点模板、文案公式、SEO 规则 |
| 06 | 表述边界 | 风控与治理 | 红线、灰色地带、法律合规、审核流程 |
| 07 | 整合输出 | 交付物 | BKB 完整版、快速参考卡 |

### 命名约定

| 对象 | 规则 | ✅ 正确 | ❌ 错误 |
|------|------|---------|---------|
| 目录名 | `NN-语义`，中文，≤4字 | `03-声调语言` | `Phase-3-Tone` |
| 文件名 | 中文，短横分隔，≤15字 | `声调三轴.md` | `Tone_Axis_v3_final.md` |
| 版本 | 由 Git 管理，不写进文件名 | — | `20260622-声调三轴.md` |

### 三条原则

1. **产出入架** — 做什么随意，产出后归入对应 Phase
2. **不恋战** — 同一个方向 3 轮没结论就打 `[假设]` 标记，先放着
3. **Parking Lot** — "可能有用但暂时不需要"的想法，记入 `parking-lot.md`

### 维护机制

**手动触发。** 本知识库的所有更新均由人手动发起。不存在自动同步、定时扫描或后台维护。触发点只有一个：你告诉我「更新一下」。

---

## 二、全量关系索引

| 节点 | 阶段 | 上游输入 | 下游产出 | 跨层关联 |
|------|------|----------|----------|----------|
| 基础档案 | 00 | — | 01-市场定位 | — |
| 市场环境与竞品分析 | 01 | 00-基础档案 | 目标人群画像 | — |
| 目标人群画像 | 01 | 市场环境与竞品分析 | 品牌定位陈述 | — |
| 品牌定位陈述 | 01 | 目标人群画像 | 02-核心价值观 | 03-声调语言 |
| 核心价值观 | 02 | 品牌定位陈述 | 使命与愿景 | — |
| 使命与愿景 | 02 | 核心价值观 | 品牌人格 | — |
| 品牌人格 | 02 | 使命与愿景 | 03-声调语言 | — |
| 声调与语言体系 | 03 | 02-品牌人格 | 04-视觉调性 | 02-核心价值观 |
| LinkedIn 主页 | 05 | 03-声调语言 | — | 02-使命愿景, 02-核心价值观 |
| Twitter/X 主页 | 05 | 03-声调语言 | — | 02-使命愿景, 02-核心价值观 |
| TCShell 主题 | 04 | 视觉调性 | — | 00-基础档案 |

### 节点详情

#### 00-基础档案/基础档案.md
- **状态：** draft
- **功能：** 品牌基本信息、业务理解、待明确问题

#### 01-市场定位/市场环境与竞品分析.md
- **状态：** draft
- **功能：** 市场格局判断 + 三家竞品（MeUp / WhitePress / BaZoom）详细对比

#### 01-市场定位/目标人群画像.md
- **状态：** draft
- **功能：** 客户细分矩阵（小站/中大型企业/Agency）+ 当前全覆盖策略

#### 01-市场定位/品牌定位陈述.md
- **状态：** draft
- **功能：** 品牌定位句 + 定位三角 + 差异化逻辑

#### 02-价值观人格/核心价值观.md
- **状态：** draft
- **功能：** 五个核心价值观（诚信为先/客户成功/人本驱动/持续进化/价值共创）

#### 02-价值观人格/使命与愿景.md
- **状态：** confirmed
- **功能：** 使命与愿景定义

#### 02-价值观人格/品牌人格.md
- **状态：** confirmed
- **功能：** 智者+实干家 人格模型

#### 03-声调语言/声调与语言体系.md
- **状态：** draft
- **功能：** 声调三轴、场景偏移规则、边界场景指南、语言风格、关键词/禁用词

#### 04-视觉体系/TC-Simple theme/
- **状态：** active
- **功能：** TraffiClimb 网站主题（TCShell v0.7.1.10+）

#### 05-内容模板/LinkedIn-公司主页.md
- **状态：** draft
- **功能：** LinkedIn 公司主页 About / Specialties 文案草案

#### 05-内容模板/Twitter-X-主页.md
- **状态：** confirmed
- **功能：** X 平台 Bio / 内容支柱 / 示例帖子

---

## 三、构建计划（已归档）

> 原始构建计划，已被 README.md 取代。

### 整体映射逻辑

```
市场研究 ──→ 品牌定位 ──→ 核心价值 ──→ 人格与声调 ──→ 语言体系 ──→ 视觉体系 ──→ 模板框架 ──→ 表述边界 ──→ BKB 终稿
```

每层产出是下一层的输入，不允许跳过。

### 执行规则

1. 严格按照 Phase 顺序推进，**不跳层**
2. 每个 Phase 完成后，你确认通过，再进下一层
3. 每条产出要求"有例子、有对照、可执行"
4. 同一个方向 3 轮没结论 → 标记 `[假设：xxx]`，继续推进
5. 所有"可能有用但暂时不需要"的想法 → `parking-lot.md`

### Parking Lot

_当前为空。_

---

## 四、Phase 00 — 基础档案

### 品牌基本信息

| 项目 | 内容 |
|------|------|
| 品牌名称 | TraffiClimb |
| 简称 | TC |
| 业务本质 | 外链聚合商（Backlink Aggregator） |
| 对外定位 | Link Building 服务商 |
| 目标市场 | 欧美市场 |
| 网站 | https://www.trafficlimb.com |

### 业务理解

**做什么：** 提供外链建设服务——从专业品牌角度，是 Link Building 服务商，为客户提供高质量外链资源与链接建设策略。

**客户是谁：** 欧美市场的网站所有者、SEO 从业者、数字营销团队、机构代理。

**目标客户细分：**

| 类型 | 说明 |
|------|------|
| 个人小站 | 独立站长、个人博客/利基站，需要 affordable 的外链资源 |
| 中大型企业自有团队 | 有 in-house SEO 团队，需要批量高质量外链 + 策略支持 |
| 代理方（Agency） | 数字营销代理，为客户采购外链，需要可靠的白标或渠道合作 |

> 当前阶段：业务建设期。策略是营造全面品牌形象，覆盖所有细分市场，不设限。

### 待明确问题

- [ ] 品牌已有材料？旧版手册 / VI / 文案样本
- [ ] 品牌已有视觉资产？（Logo / 色系 / 网站）
- [ ] BKB 最终使用者？（市场团队 / 销售 / 内容团队 / 代理）
- [ ] 品牌当前在对外表达上的痛点

---

## 五、Phase 01 — 市场定位

### 5.1 市场环境与竞品分析

#### 市场环境判断

**整体格局：红海中的产业转型期**

Link Building 市场整体处于红海阶段：玩家众多，低端市场价格战激烈；PBN、垃圾外链、自动化批量发链等模式在被算法清洗；Google 核心更新 + AI/GEO 冲击，旧玩法加速失效。

**细分机会：高端合规 + 内容驱动**

市场需求没有消失，而是在"从量到质"转型：
- 低端外链价值持续贬值，高端外链（PR 级、内容原生嵌入）价值上升
- GEO 时代内容质量权重更高，外链策略从"数量爬升"转向"精准关联"
- 欧洲等地监管严格的环境下，合规本身就是一道壁垒
- 产业转型期 = 新格局正在形成，窗口期存在

**对 TraffiClimb 的意义：** 转型期有利于低端玩家清洗 → 市场教育成本降低 → 客户更清楚"值得花钱的链接"长什么样 → 合规 + 高端 + 内容三角 = TC 可以卡位的生态位。

#### 竞品 1：MeUp (meup.com)

| 维度 | 内容 |
|------|------|
| 定位 | "#1 Link Building Platform" — DIY 选购 + 全托管服务 |
| 规模 | 150,000+ 审核站点、80,000+ 独立域名 |
| 模式 | Marketplace（自助选购）+ Managed（专家托管）双模式 |
| 技术整合 | 深度对接 Moz、Ahrefs、SEMrush 数据 |
| 目标客户 | 从个人到 agency 全覆盖 |
| 信任信号 | Trustpilot 评价、SEO veterans 团队背景、Intercom 客服 |
| 视觉风格 | 现代、绿色主色调、Plus Jakarta Sans 字体、Elementor |
| 优势 | 平台规模大、工具整合深、双模式覆盖广 |
| 弱点 | Marketplace 模式偏"超市化"，高端定制感可能不足 |

#### 竞品 2：WhitePress (whitepress.com)

| 维度 | 内容 |
|------|------|
| 定位 | "Global link building platform" — SEO + link building + Digital PR |
| 成立 | 2013 年（波兰公司，伦敦注册） |
| 规模 | 26+ 语言市场，全球覆盖 |
| 模式 | Marketplace + 内容营销 + PR 一体 |
| 独特卖点 | 同时覆盖 Google 搜索 + ChatGPT/AI Overviews 可见性 |
| 客户 | SEO 团队、link builders、网站主、营销人员 |
| 内容布局 | 有 SEO VIBES Podcast 等内容品牌动作 |
| 视觉风格 | 黑红配色的专业感，偏传统 B2B SaaS |
| 优势 | 国际化深度（26+ 语种）、成立时间长（13年）、覆盖 AI 可见性 |
| 弱点 | 偏平台化而非深度服务、个性化程度可能有限 |

#### 竞品 3：BaZoom (bazoom.com)

| 维度 | 内容 |
|------|------|
| 定位 | "Your Trusted Link Building Service Agency" — **人驱动的服务商**，而非纯平台 |
| 总部 | 丹麦奥胡斯（HQ）+ 哥本哈根 + 美国迈阿密 |
| 公司 | Bazoom Group / Founder: Nicolai Klausen / 80+ 员工 |
| 模式 | Marketplace + 全托管服务（Intelligent Marketplace / Content Engine / Strategy Builder） |
| 核心差异 | "Powered by people – not just a marketplace!" — 强调人工服务与个人合作 |
| 定价 | 无订阅/入门费，按链接付费，价格含内容+发布 |
| 媒体网络 | 80,000+ 媒体渠道 |
| 客户细分 | Consultants / Agencies / Direct Clients / Affiliates / Newcomers / Media Outlets |
| 信任信号 | G2 Badges、Astralis 联名、Trustpilot 5★ |
| 发布速度 | 平均 4 天 |
| 优势 | 明确的人 vs 平台差异化、客户评价高、80+ 团队、多地办公 |
| 弱点 | 偏北欧/欧洲起家，品牌声量可能不如 MeUp |

#### 竞品定位图谱

```
高定制 / 深度服务
        ↑
        |    BaZoom        [TraffiClimb 目标位置]
        |   (人驱动服务)
        |
        |                      MeUp
        |                    (双模式)
        |
        |         WhitePress
        |       (国际化平台)
        |
低定制 / 自助平台
        └─────────────────────────→
        低端/批量              高端/PR级
```

#### 差异化机会

| 维度 | 竞品现状 | TC 可切的角度 |
|------|----------|--------------|
| 服务深度 | 偏自助/半托管 | 全流程深度服务 + 策略咨询 |
| 内容整合 | 内容与链接分离 | 内容创作 → 链接获取 → PR 一体 |
| GEO 适配 | 开始提及但早期 | 深度融入 GEO/AI 内容策略 |
| 合规壁垒 | 一般性合规 | 聚焦欧洲合规市场做护城河 |
| 品牌人格 | SaaS 平台感重 | 更有人格化的品牌叙事 |

---

### 5.2 目标人群画像

**当前策略：不挑客户，全覆盖。语言层面不要过于张扬自己的全覆盖，合理范围即可**

#### 客户细分矩阵

| 类型              | 典型角色                    | 核心需求                  | 购买决策特点                          | TC 切入角度              |
| --------------- | ----------------------- | --------------------- | ------------------------------- | -------------------- |
| **个人小站**        | 独立站长、个人博客、利基站主          | Affordable 高质量外链、简单直接 | 价格敏感、自助倾向、快速见效                  | 低门槛入场、清晰定价、自助+轻托管    |
| **中大型企业自有团队**   | In-house SEO 经理、数字营销负责人 | 批量高质量外链、策略对齐、合规保障     | 流程规范、看重汇报与数据、long-term contract | 策略咨询 + 批量交付 + 数据透明   |
| **Agency（代理方）** | 数字营销 agency 采购/策略负责人    | 白标合作、稳定供应、价格空间        | 量大、注重 reliability 和 margin、需要白标 | 白标计划、API/平台接入、专属客户经理 |

#### 共通特征（欧美市场）

| 维度 | 描述 |
|------|------|
| 语言 | 英语为主 |
| 痛点 | 高质量外链难获取、低质链接被算法惩罚、供应商不稳定 |
| 价值观 | 看重合规、透明度、结果可衡量 |
| 决策路径 | 搜索 → 内容/评价 → 对比 → 试用/咨询 → 下单 |
| 信任要素 | Trustpilot / G2 评分、Case Study、团队背景、透明报价 |

---

### 5.3 品牌定位陈述

#### 定位句（草案）

> **TraffiClimb** 为全球范围内的网站所有者、SEO 团队和数字营销代理提供 **合规、内容驱动的高端外链解决方案**，帮助他们在搜索引擎和 AI 搜索时代获得可持续的排名增长。

#### 定位三角

| 维度 | 内容 |
|------|------|
| **目标客户** | 从小站到企业的全链路 Link Building 需求方 |
| **提供的价值** | 合规安全 + 内容驱动 + 高端外链资源 |
| **差异化** | 不只是一家 marketplace——是策略伙伴，兼顾规模与深度 |

#### Tagline

> **Your strategic partner for premium link building.**

#### 关键词标签

`合规` / `Compliant` · `内容驱动` / `Content-Driven` · `高端外链` / `Premium Backlinks` · `策略伙伴` / `Strategic Partner` · `全球覆盖` / `Global Reach` · `可持续发展` / `Sustainable Growth`

---

## 六、Phase 02 — 价值观与人格

### 6.1 核心价值观

| 价值观 | 英文 | 说明 |
|--------|------|------|
| **诚信为先** | Integrity First | 合规为本，透明为习。不碰低质，不诺空言 |
| **客户成功** | Client Success | 不卖链接，只促增长 |
| **人本驱动** | People-Driven | 不推诿，有人兜底。凡事"我来处理" |
| **持续进化** | Continuous Growth | 持续学习，拥抱变化。更新是机会，不是恐慌 |
| **价值共创** | Value Creation | 不止交付，持续输出。共同成长 |

> 状态：待确认

### 6.2 使命与愿景

**使命：** 让每一个有理想的品牌被世界看见。
**Mission:** Help every ambitious brand be seen by the world.

**愿景：** 全球最受信任的外链增长伙伴。
**Vision:** The world's most trusted link building growth partner.

> 状态：已确认 ✅

### 6.3 品牌人格

**方案：智者 + 实干家（已确认 ✅）**

既专业可信，又不玩虚的。对外给人的感觉：
- 专业但不傲慢
- 靠谱但不无聊
- 有温度但不煽情

#### 人格对照表

| 维度 | TC 的位置 | 不是 |
|------|----------|------|
| 正式 ↔ 轻松 | 偏正式，但有亲和力 | 不是冷冰冰的 corporate |
| 权威 ↔ 亲切 | 权威来自专业，而非姿态 | 不是"我是专家你听我的" |
| 冷静 ↔ 热情 | 冷静做事，热情服务 | 不是过度热情式销售 |
| 传统 ↔ 创新 | 方法扎实，认知前沿 | 不是守旧派，也不是追风口 |

---

## 七、Phase 03 — 声调与语言体系

### 7.1 声调三轴

| 轴 | 定位 | 不是 |
|----|------|------|
| 正式 ↔ 轻松 | 偏正式，但有亲和力 | 冷冰冰的 corporate |
| 权威 ↔ 亲切 | 权威来自专业，而非姿态 | "我是专家你听我的" |
| 冷静 ↔ 热情 | 冷静做事，热情服务 | 过度热情式销售 |

### 7.2 场景偏移规则

不同场景下三条轴可适度偏移，但幅度不超过一格：

| 场景 | 正式↔轻松 | 权威↔亲切 | 冷静↔热情 | 说明 |
|------|----------|----------|----------|------|
| 官网首页 / Landing Page | ← 偏正式 | ↕ 中性 | → 偏热情 | 建立信任，传递价值 |
| 博客 / 教育内容 | → 偏轻松 | → 偏亲切 | ↕ 中性 | 降低阅读门槛 |
| 销售页 / CTA | ↕ 中性 | ← 偏权威 | → 偏热情 | 给决策信心 |
| 客服 / 售后 | → 偏轻松 | → 偏亲切 | → 偏热情 | 有人情味 |
| 错误 / 问题沟通 | ↕ 中性 | ↕ 中性 | ↕ 中性 | 冷静专业，不推诿 |

> 偏移是弹性，不是变人格。底色始终是"懂行、靠谱、有温度"。

### 7.3 边界场景声调指南

#### 场景 1：客户异议

**原则：** 不反驳，不降价自贬。先认可，再解释价值。

| ✅ 对 | ❌ 不对 |
|------|--------|
| "I hear you. Let me break down what's included and why it makes a difference." | "Our prices are actually very competitive if you compare." |
| "That's a fair concern. Here's what our clients typically see in terms of ROI—" | "Sorry, that's the best we can do." |

#### 场景 2：质疑效果

**原则：** 诚实面对 timeline，用数据说话，不给空承诺。

| ✅ 对 | ❌ 不对 |
|------|--------|
| "Link building typically takes 3–6 months to show measurable impact. Here's where we stand right now—" | "Don't worry, it's working. Just give it more time." |
| "Based on similar campaigns, here's the trajectory we expect." | "SEO takes time, you just have to be patient." |

#### 场景 3：客户抱怨

**原则：** 先听，再认，再解决。不解释、不辩解、不推卸。

| ✅ 对 | ❌ 不对 |
|------|--------|
| "I understand why that's frustrating. Let me look into it and get back to you with a solution within 24 hours." | "Actually, this is a high-DA site, the link is perfectly fine." |
| "You're right to expect better. Let me fix this." | "That's not really our fault, it's the publisher's choice." |

#### 场景 4：同行对比

**原则：** 不贬低对手。承认对方价值，然后清晰说出自己的不同。

| ✅ 对 | ❌ 不对 |
|------|--------|
| "They're a solid platform. Where we differ is our approach to strategy and ongoing support." | "They're not as good as us. Their links are lower quality." |
| "If volume is your priority, they might be a fit. If you want a partner who works alongside your team, that's what we do." | "We're better in every way." |

#### 边界场景通用原则

> **先接住情绪，再处理问题。先认可，再引导。**
> 无论客户说什么——不反驳、不争输赢、不扔空话。

#### 观念冲突处理公式

| 步骤 | 做什么 | 不做什么 |
|------|--------|----------|
| ① 认可 | 先确认客户的角度是对的 | 不说"but"、"however"、"不过"等转折词 |
| ② 带入 | 自然地引出你的角度，并解释它的由来 | 不要暗示对方的视角是错的 |
| ③ 低姿态坚持 | 实事求是地保持你的判断，不迎合 | 不要因为认可对方就放弃自己的立场 |
| ④ 交还决策 | 把选择权交给客户 | 不要替客户做决定 |

### 7.4 语言风格示例

| 场景 | ✅ 对 | ❌ 不对 |
|------|------|--------|
| 介绍服务 | "We build high-quality backlinks that drive sustainable growth." | "We'll get you to #1 in Google overnight." |
| 讲合规 | "Every placement follows search engine guidelines." | "Don't worry, Google won't find out." |
| 讲价格 | "Simple pricing. You only pay for what works." | "Contact us for a quote (probably expensive)." |
| 客户问题 | "Let's look into this and get it sorted." | "That's not our responsibility." |
| 宣传成果 | "We've helped 500+ sites improve their organic visibility." | "We're the best. Trust us." |

### 7.5 关键词汇表

| 类别 | 词汇 | 用法说明 |
|------|------|----------|
| **必用词** | premium, compliant, sustainable, growth, strategic | 贯穿所有对外文案 |
| **推荐词** | transparent, partnership, long-term, quality, results-driven | 丰富表达时优先用 |
| **场景词** | actionable, tailored, scalable | 适用于销售/方案场景 |

### 7.6 禁用词表

| 级别 | 词 | 原因 |
|------|-----|------|
| 🚫 绝对不说 | guaranteed #1, overnight, instant results, foolproof | 不真实，损害信任 |
| 🚫 绝对不说 | cheap, budget, low-quality | 与高端定位冲突 |
| 🚫 绝对不说 | spammy links, PBN, black hat | 暗示灰色操作 |
| ⚠️ 尽量避免 | "we think", "maybe", "kind of" | 削弱专业感（客服场景可例外） |
| ⚠️ 尽量避免 | 过度感叹号（!!）、全大写承诺 | 看起来像营销垃圾 |

### 7.7 修辞偏好

- **数据说话** — 用数字和案例替代空洞形容词
- **短句优先** — 不写长难句，不炫技
- **主动语态** — "We built this" 胜过 "This was built by us"
- **直接称呼** — 多用 "you/your" 和 "we/our"，减少被动冷感
- **适度类比** — 可以讲人话，但不堆比喻

### 7.8 语种策略

当前以 **英文** 为主（欧美市场）。中文版本定位为内部参考/中文市场备用，风格保持一致。

> 状态：待确认

---

## 八、Phase 04 — 视觉体系

### 品牌主题：TCShell

| 项目 | 内容 |
|------|------|
| 主题名 | TCShell |
| 当前版本 | v0.7.3.3（style.css 记录） |
| 源码目录 | `04-视觉体系/TC-Simple theme/ActivatedVersion/` |
| 版本记录 | `04-视觉体系/TC-Simple theme/VersionRecord/` |
| 网站 | https://www.trafficlimb.com |

### 架构：两层模型

1. **Theme（shell）** — `design-tokens.css` + `shell.css` + `site.js`
   - 每页都加载：header、footer、modal、chrome buttons、layout shell
2. **Content（local）** — 页面 Custom HTML 内嵌样式
   - 内页：`tc-page-base.css` 内联在每个页面的 HTML 中
   - 首页：`#tc-home-pro-styles` / `#tc-home-pro-script` 自包含

### 设计系统核心

见 `DESIGN-SYSTEM.md`：
- **Design tokens**：全站色板、字号、间距、按钮尺寸，集中在 `design-tokens.css`
- **Shell**：只含网站 chrome（reset, body, header, footer, modal, 壳层按钮）
- **页面基础**：Service/FAQ/Contact/Blog 区块样式，通过 `tc-page-base.css` 注入
- **首页**：完全自包含（`#tc-home-pro`），不依赖主题的区块样式

### 主题职责分配

| 改什么 | 改哪里 |
|--------|--------|
| 全站色/字 | `design-tokens.css` |
| 页眉/页脚/弹窗/壳层按钮 | `shell.css` + `header.php` / `footer.php` |
| 内页区块 | `tc-page-base.css` → `build-inject-page-styles.py` |
| 首页 | 独立 HTML → 复制粘贴到 WP |

> 详细开发文档见知识库原目录：
> - `THEME-SHELL-REQUIREMENTS.md` — 轻主题 vs 重页面约定
> - `CUSTOM-HTML-SCRIPTS.md` — 内联 `<script>` 处理方案
> - `SHORTCODES.md` — 博客文章列表 shortcode 参考

---

## 九、Phase 05 — 内容模板

### 9.1 LinkedIn 公司主页

| 字段 | 内容 |
|------|------|
| 名称 | TraffiClimb |
| Tagline | Your strategic partner for premium link building. |
| 行业 | Marketing & Advertising |
| 规模 | 11–50 人 |

**About — 方案 A（推荐）：**

> At TraffiClimb, we help ambitious brands build their visibility through premium link building strategies.
>
> We don't just place links—we build partnerships. Every campaign is backed by real strategy, transparent reporting, and a team that takes ownership.
>
> Whether you're a growing startup, an in-house SEO team, or a digital agency, we deliver link building that drives measurable, sustainable growth.
>
> Your strategic partner for premium link building. 🚀

**About — 方案 B（结果为主型）：**

> 500+ sites improved. Millions in organic traffic generated. One partnership at a time.
>
> TraffiClimb is a link building agency built for the modern search landscape. We combine compliance-first practices with content-driven strategies to help our clients rank higher, grow faster, and stay ahead of algorithm changes.
>
> From startups to agencies—we scale with you.

**Specialties：**

```
Link Building, SEO, Digital PR, Content Marketing, Backlink Strategy,
Search Engine Optimization, Growth Marketing, Premium Backlinks,
Content Outreach, Organic Growth
```

**待办：** 确认总部地址、上传 Logo + Banner、选定 About 方案

### 9.2 Twitter / X 主页

**Bio（已确认 ✅）：**

> Your strategic partner for premium link building.
> Helping ambitious brands be seen by the world.
>
> *(106 chars)*

**内容支柱比例：**

| 类型 | 占比 | 内容方向 |
|------|------|----------|
| 教育 | 40% | Link building tips, SEO insights, GEO trends |
| 品牌 | 25% | Case studies, client wins, behind the scenes |
| 观点 | 20% | Industry takes, thought leadership |
| 互动 | 15% | Polls, questions, replies, engagement |

**示例帖子：**

教育型：
> Most people think link building is about quantity.
> It's not.
> One relevant, high-quality link beats 50 spammy ones every time.

品牌型：
> Just wrapped up a campaign that moved a client's organic traffic by +180% in 4 months.
> No shortcuts. Just consistent, quality placements.

观点型：
> SEO in 2026 = content + links + adaptability.
> If you're still using 2020 strategies, you're already behind.

---

## 十、Phase 06 / 07 — 待建设

以下两个 Phase 暂未开始：

| Phase | 目录 | 内容 |
|-------|------|------|
| 06 | 表述边界 | 红线、灰色地带、法律合规、审核流程 |
| 07 | 整合输出 | BKB 完整版、快速参考卡 |

---

> **汇总日期：** 2026-06-26
> **知识库路径：** `/home/buzzezz/Zone/Crow/TC知识库.md`
> **源目录：** `/home/buzzezz/Zone/Crow/追踪/TC-品牌知识库/`
