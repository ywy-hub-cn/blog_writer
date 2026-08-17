# BID 校验规则（P0硬约束）

## 一、结构完整性校验

### 1.1 必须包含的顶层字段
- `bid`: BID 7层标识对象
- `summary`: 摘要信息对象
- `validation`: 校验结果对象（初始为 `{"passed": false, "issues": []}`）

### 1.2 bid对象必须包含的层
- `core`（CO层）：13个点位，全部必填且非空
- `web`（WB层）：7个点位，全部必填且非空
- `seo`（SE层）：7个点位，全部必填且非空
- `geo`（GE层）：5个点位，全部必填且非空
- `cl`（CL层）：6个点位，全部必填（允许值为 "N/A"）
- `lo`（LO层）：必填且非空
- `st`（ST层）：必填且非空

## 二、CO层（内容核心）校验规则

### 2.1 必填字段（13个）
| 字段 | 含义 | 示例 |
|------|------|------|
| at | 文章类型 | blog / guide / comparison |
| th | 主题 | "SMS gateway comparison" |
| pi | 内容意图 | comparison / tutorial / guide |
| ct | 内容类型 | comparison / tutorial / guide |
| pv | 专业程度 | technical / non_technical |
| pr | 目标读者 | developer / marketer / executive |
| al | 受众水平 | beginner / intermediate / advanced |
| dp | 深度 | introductory / comprehensive / deep_dive |
| tm | 语气 | professional / casual / friendly |
| fm | 格式 | shortform / longform / listicle |
| tn | 叙述者角色 | trusted_expert / peer / mentor |
| so | 信息来源 | brand_expertise / data_driven |
| ev | 证据类型 | data_case / customer_story |

### 2.2 约束
- 所有字段必须从 bid-system.md 枚举值中选择
- th（主题）是自由文本，其他字段必须是枚举值
- 字段值使用小写下划线格式

## 三、WB层（业务目标）校验规则

### 3.1 必填字段（7个）
| 字段 | 含义 | 示例 |
|------|------|------|
| obj | 业务目标 | lead_generation / brand_awareness |
| uc | 用户转化 | demo_request / free_trial |
| js | 购买阶段 | awareness / consideration / decision |
| cta | 行动号召 | request_demo / start_free_trial |
| ci | 内容意图 | solution_education / product_comparison |
| pm | 推广方式 | organic / paid / social |
| rk | 排名目标 | top_3 / top_10 / page_1 |

### 3.2 约束
- 所有字段必须从枚举值中选择
- obj与js应匹配：awareness阶段对应brand_awareness，decision阶段对应lead_generation/conversion

## 四、SE层（SEO）校验规则

### 4.1 必填字段（7个）
| 字段 | 含义 | 示例 |
|------|------|------|
| si | 搜索意图 | informational / commercial_investigational |
| qs | 查询类型 | comparison / how_to / what_is |
| kl | 关键词长度 | short_tail / medium_tail / long_tail |
| kc | 关键词分类 | informational / commercial_investigational |
| sf | 漏斗阶段 | top_funnel / middle_funnel / bottom_funnel |
| sc | 搜索分类 | b2b_technical / b2b_business |
| ic | 意图分类 | educational / comparative / promotional |

### 4.2 约束
- si与kc应一致：informational对应informational，commercial_investigational对应commercial_investigational
- sf与js应匹配：top_funnel对应awareness，bottom_funnel对应decision

## 五、GE层（GEO）校验规则

### 5.1 必填字段（5个）
| 字段 | 含义 | 示例 |
|------|------|------|
| gi | 信息来源类型 | reference_source / primary_source |
| gs | 来源可信度 | authoritative / credible / popular |
| gf | 来源权重 | high / medium / low |
| gn | 来源性质 | brand_authority / thought_leadership |
| gc | 可引用性 | citable / quotable / linkable |

### 5.2 约束
- 所有字段必须从枚举值中选择
- gi为reference_source时，gs应为authoritative或credible

## 六、CL层（集群）校验规则

### 6.1 必填字段（6个）
| 字段 | 含义 | 示例 |
|------|------|------|
| pi | 集群ID | "00"（无集群）/ "01"（集群1） |
| sub | 子集群ID | "00"（无子集群） |
| cr | 集群角色 | "N/A" / "pillar" / "cluster" |
| il | 内链层级 | "N/A" |
| lt | 链接类型 | "N/A" |
| pf | 优先级因子 | "01" |

### 6.2 约束
- 无集群信息时，pi和sub为 "00"，cr/il/lt为 "N/A"
- pf为数字字符串，如 "01"、"02"

## 七、LO层（语言）校验规则

- 必须是枚举值：01（英语）/ 02（中文）/ 03（西班牙语）/ 04（法语）/ 05（德语）
- 根据目标市场和品牌定位选择

## 八、ST层（结构模板）校验规则

- 必须是枚举值：comparison_guide / how_to_guide / product_review / case_study / tutorial / checklist / glossary / landing_page / blog_post / news_article / opinion_piece / interview
- 应与CO层的pi/ct匹配：comparison意图对应comparison_guide，tutorial意图对应how_to_guide/tutorial

## 九、summary层校验规则

### 9.1 必填字段
- `title`: 文章标题（非空）
- `slug`: URL slug（非空，小写连字符格式）
- `keyword`: 目标关键词（非空）

### 9.2 可选但推荐字段
- `seo_title`: SEO标题（≤60字符）
- `meta_description`: 元描述（≤160字符，必须包含关键词）
- `excerpt`: 摘要
- `structure_template_name`: 结构模板名称
- `tone`: 语气描述
- `depth`: 深度描述
- `audience`: 受众描述

### 9.3 约束
- meta_description如果存在，必须包含keyword（不区分大小写）
- slug应为小写，使用连字符分隔，不含特殊字符

## 十、validation层校验规则

- 初始值：`{"passed": false, "issues": []}`
- 由validate_bid.py脚本校验通过后设置为 `{"passed": true, "issues": []}`
- LLM不得自行设置passed为true

## 十一、常见错误

1. ❌ 字段值自由发挥，未使用枚举值
2. ❌ 缺少必填字段
3. ❌ 字段值为空字符串
4. ❌ CL层无集群时未使用 "N/A"
5. ❌ meta_description不包含关键词
6. ❌ validation.passed被LLM自行设为true
7. ❌ 枚举值使用大写或空格格式（应为小写下划线）
8. ❌ slug包含大写或特殊字符

## 十二、校验通过标准

所有P0硬约束全部满足，且无任何错误，才能通过校验。任何一项不满足都需要修正后重新校验。
