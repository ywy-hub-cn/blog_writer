# HTML 输出规范 — 设计系统

> 发布于 S006 呈现文档和 S010 发布包的最终 HTML

---

## 一、颜色系统

| 颜色角色 | 色值 |
|---------|------|
| 主绿色 | #5D765F |
| Hover 深绿色 | #4D6350 |
| 深绿色 | #3F5242 |
| 浅绿色背景 | #EEF3EC |
| 更浅绿色背景 | #F5F8F3 |
| 主标题色 | #132019 |
| 次级标题色 | #213027 |
| 正文色 | #39433C |
| 辅助文字色 | #687268 |
| Section 背景 | #FBFCF8 |
| FAQ 问题背景 | #F1F5EF |
| FAQ 答案背景 | #F6F8F3 |
| 普通边框色 | #DFE2DA |
| 浅绿边框色 | #C9D5C5 |
| References 背景 | #F1F3ED |

---

## 二、正文字体

| 项目 | 内容 |
|------|------|
| 字体 | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto |
| 备用字体 | Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif |
| 正文颜色 | #39433C |
| 字重 | 400 |
| 字体风格 | WordPress 默认无衬线、简洁、低装饰 |

---

## 三、正文段落

| 项目 | 桌面端 |
|------|--------|
| 字号 | 19px |
| 行高 | 1.74 |
| 段落下间距 | 20px |
| 字重 | 400 |
| 颜色 | #39433C |

**首段样式：** 字号 20px–21px，行高 1.6–1.65，颜色 #2D3831
**移动端：** 正文字号 17px，首段字号 18px，行高 1.65–1.72

---

## 四、HTML 标题层级规范

### H1 文章主标题

| 项目 | 内容 |
|------|------|
| 字体 | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto |
| 备用 | Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif |
| 说明 | 必须与 H2/H3 使用相同的 font-family，不得用 serif 字体 |
| 字号 | clamp(38px, 4vw, 52px) |
| 字重 | 600 |
| 行高 | 1.08 |
| 字间距 | -0.02em |
| 颜色 | #132019 |
| 下方间距 | 32px |
| 背景 | 透明 |
| 样式 | 纯文字标题，无背景色块 |

### H2 主章节标题

| 项目 | 内容 |
|------|------|
| 字体 | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto |
| 备用 | Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif |
| 字号 | clamp(32px, 3vw, 44px) |
| 字重 | 600 |
| 行高 | 1.12 |
| 字间距 | -0.035em |
| 颜色 | #132019 |
| 上方间距 | 78px |
| 下方间距 | 32px |
| 背景 | 透明 |
| 样式 | 纯文字标题 |
| 目录关系 | Elementor Table of Contents 默认读取对象 |

### H3 次级标题

| 项目 | 内容 |
|------|------|
| 字体 | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto |
| 备用 | Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif |
| 字号 | clamp(22px, 1.8vw, 27px) |
| 字重 | 600 |
| 行高 | 1.28 |
| 字间距 | -0.012em |
| 颜色 | #213027 |
| 上方间距 | 48px |
| 下方间距 | 16px |
| 背景 | 透明 |
| 样式 | 纯文字标题 |

### 移动端标题

| 标题 | 字号 | 上方间距 | 下方间距 |
|------|------|---------|---------|
| H2 | 31px | 58px | 24px |
| H3 | 23px | 38px | 16px |

---

## 五、HTML 列表规范

### 列表容器

| 项目 | 内容 |
|------|------|
| 背景色 | #EEF3EC |
| 边框 | 1px solid #C9D5C5 |
| 圆角 | 18px |
| 内边距 | 22px 26px 22px 36px |
| 外边距 | 22px 0 32px |

### 列表文字

| 项目 | 内容 |
|------|------|
| 字号 | 19px |
| 行高 | 1.62 |
| 颜色 | #39433C |
| marker 颜色 | #3F5242 |
| marker 字重 | 700 |
| 单项间距 | 9px |

---

## 六、HTML FAQ 模块规范

### FAQ 模块结构

使用原生 HTML `<details>` 折叠结构：

```html
<section class="faq-section">
  <h2>FAQ</h2>
  <div class="faq-list">
    <details class="faq-item" open>
      <summary>Question text</summary>
      <div class="faq-answer">
        <p>Answer text...</p>
      </div>
    </details>
  </div>
</section>
```

### FAQ 外层样式

| 项目 | 内容 |
|------|------|
| 背景 | #FBFCF8 |
| 边框 | 1px solid #DFE2DA |
| 圆角 | 24px |
| 内边距 | 34px |
| 上方间距 | 76px |

### FAQ 标题

| 项目 | 内容 |
|------|------|
| 字体 | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto |
| 备用 | Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif |
| 字号 | clamp(30px, 2.8vw, 40px) |
| 字重 | 600 |
| 行高 | 1.14 |
| 字间距 | -0.03em |
| 颜色 | #132019 |
| 下方间距 | 26px |

### FAQ 问题卡片

| 项目 | 内容 |
|------|------|
| 背景 | #F1F5EF |
| 边框 | 1px solid #C9D5C5 |
| 圆角 | 18px |
| 间距 | 14px |
| 问题字号 | 19px |
| 问题行高 | 1.35 |
| 问题字重 | 500 |
| 问题颜色 | #132019 |
| 内边距 | 18px 48px 18px 20px |

### FAQ 答案区域

| 项目 | 内容 |
|------|------|
| 背景 | #F6F8F3 |
| 顶部分割线 | 1px solid #C9D5C5 |
| 内边距 | 18px 20px 20px |
| 答案字号 | 17px |
| 答案行高 | 1.64 |
| 答案颜色 | #39433C |

---

## 七、HTML References 模块规范

### References 模块结构

```html
<section class="references-section">
  <h2>References</h2>
  <div class="references-list">
    <div class="reference-item">
      <span class="reference-number">[1]</span>
      <p>Reference description...</p>
    </div>
  </div>
</section>
```

### References 外层样式

| 项目 | 内容 |
|------|------|
| 背景 | #FBFCF8 |
| 边框 | 1px solid #DFE2DA |
| 圆角 | 24px |
| 内边距 | 34px |
| 上方间距 | 34px 或 76px |

### References 标题

| 项目 | 内容 |
|------|------|
| 字体 | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto |
| 备用 | Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif |
| 字号 | clamp(30px, 2.8vw, 40px) |
| 字重 | 600 |
| 行高 | 1.14 |
| 颜色 | #132019 |
| 下方间距 | 26px |

### Reference 条目卡片

| 项目 | 内容 |
|------|------|
| 背景 | #F1F3ED |
| 边框 | 1px solid #DFE2DA |
| 圆角 | 14px |
| 内边距 | 14px 16px |
| 条目间距 | 12px |
| 布局 | 编号 + 正文 |

### Reference 编号

| 项目 | 内容 |
|------|------|
| 字号 | 14px |
| 字重 | 600 |
| 颜色 | #3F5242 |
| 行高 | 1.55 |

### Reference 正文

| 项目 | 内容 |
|------|------|
| 字号 | 14px |
| 行高 | 1.58 |
| 颜色 | #687268 |
| 加粗文字颜色 | #213027 |

---

## 八、HTML 图片模块规范

### 图片基础样式

| 项目 | 内容 |
|------|------|
| 图片宽度 | 100% |
| 图片圆角 | 18px–24px |
| 上方间距 | 40px–56px |
| 下方间距 | 40px–56px |
| 图片说明字号 | 13px–14px |
| 图片说明颜色 | #687268 |

### 图片内容规则

| 项目 | 内容 |
|------|------|
| alt 文本 | 每张图片保留 |
| 图片位置 | 按正文阅读节奏插入 |
| 图片角色 | 解释、补充、总结或场景化说明 |

---

## 九、HTML Mermaid 图表模块规范

### 适用场景

| 场景 | 说明 |
|------|------|
| 流程步骤 | 文章中出现连续的多个操作步骤时，优先用 Mermaid flowchart 代替文字列表 |
| 决策树 | 需要根据条件分支判断时，用 Mermaid decision tree |
| 架构对比 | 展示系统架构、组件关系、数据流向时 |
| 时序流程 | 消息传递、API 调用链、多方交互流程时 |

### Mermaid 图表样式

| 项目 | 内容 |
|------|------|
| 图表容器圆角 | 22px |
| 图表容器背景 | #FAFAF8 |
| 图表容器边框 | 1px solid #DFE2DA |
| 标题字号 | 16px bold |
| 标题色 | #213027 |

### 配色方案

```
节点填充色: #5D765F（主绿）
节点文字色: #FFFFFF
节点边框色: #3F5242
决策节点填充色: #EEF3EC
决策节点文字色: #132019
连线色: #687268
子图标题色: #213027
```

### HTML 结构

```html
<div class="visual-mermaid" data-field="diagram" data-seq="{seq}">
  <figcaption>{图表标题说明}</figcaption>
  <div class="mermaid-container">
    <pre class="mermaid">
{MMD代码}
    </pre>
  </div>
</div>
```

### CSS

```css
.mermaid-container {
  max-width: 100%; max-height: 700px;
  overflow: auto;
  margin: 16px 0;
  border: 1px solid #DFE2DA;
  border-radius: 22px;
  background: #FAFAF8;
}
.mermaid-container pre.mermaid {
  background: #FAFAF8;
  padding: 16px;
  border-radius: 22px;
  font-size: 13px;
  margin: 0;
}
.visual-mermaid {
  margin: 40px 0;
}
.visual-mermaid figcaption {
  font-weight: 700;
  font-size: 16px;
  color: #213027;
  margin-bottom: 12px;
}
```

### CDN 注入

```html
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>mermaid.initialize({startOnLoad:true,theme:"neutral",flowchart:{useMaxWidth:true,htmlLabels:true},securityLevel:"loose"})</script>
```

---

## 十、HTML CTA 模块规范

### CTA 模块定位

CTA 作为正文内部的轻转化模块，用于承接教育型内容后的咨询、诊断、供应商评估或技术支持需求。

### CTA 样式

| 项目 | 内容 |
|------|------|
| 背景 | #EEF3EC 或 #F6F8F3 |
| 边框 | 1px solid #C9D5C5 |
| 圆角 | 22px–24px |
| 内边距 | 28px–36px |
| 标题字号 | 26px–34px |
| 正文字号 | 17px–18px |
| 按钮背景 | #3F5242 |
| 按钮文字 | #FFFFFF |
| 按钮圆角 | 999px |
| 视觉风格 | Soft Consult |

---

## S006 呈现文档 CSS 简版

```css
:root {
  --green: #5D765F;
  --green-hover: #4D6350;
  --green-dark: #3F5242;
  --green-light-bg: #EEF3EC;
  --green-lighter-bg: #F5F8F3;
  --heading-primary: #132019;
  --heading-secondary: #213027;
  --text-body: #39433C;
  --text-muted: #687268;
  --section-bg: #FBFCF8;
  --faq-question-bg: #F1F5EF;
  --faq-answer-bg: #F6F8F3;
  --border-default: #DFE2DA;
  --border-green: #C9D5C5;
  --ref-bg: #F1F3ED;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
}
```

---

## 十一、Meta Description 硬规则

### 10.1 长度规则

| 项目 | 内容 |
|------|------|
| 最大长度 | **≤ 160 英文字符** |
| 计数字符 | 空格、标点、数字、英文字母全部计入 |
| 超长处理 | 必须在输出发布包前自行压缩到 ≤160，不得原样输出后再修正 |

### 10.2 内容规则

- Meta description **不得为了塞入关键词而牺牲自然表达**
- 优先做到：
  1. 包含主关键词或接近表达
  2. 说明文章价值
  3. 控制长度 ≤160
  4. 可直接粘贴进 Yoast

### 10.3 修正规则

若发布后发现 Meta description 超长：
- **只修正 Meta description 字段**，默认不回头修改正文
- 不得因为 Meta description 超长而联动修改文章标题、SEO title 或其他字段

### 10.4 发布后自检清单

以下检查项必须包含在最终的发布包校验中：

- [ ] Meta description ≤ 160 characters

---

## 十二、正文内链样式规则

### 11.1 内链默认样式

Final article body 中的普通正文内链默认显示为绿色字体，不使用下划线样式。

**标准 CSS：**
```css
.blog-content a {
  color: #268C37;
  text-decoration: none;
  font-weight: 500;
}
.blog-content a:hover {
  color: #1F6F2C;
  text-decoration: none;
}
```

### 11.2 适用范围

| 适用 | 不适用 |
|------|--------|
| 正文段落中的自然内链 | CTA button（使用按钮样式） |
| FAQ / References 中的普通文本链接 | |
| Internal Link Card 中的普通链接 | |

### 11.3 特殊处理

- **下划线规则：** 默认无下划线。若用户明确要求某篇文章使用下划线，按用户要求执行
- **兼容性：** 规则仅针对 `Final article body` 中的链接，不影响 WordPress 全局链接样式

---

## 十三、Blog 分类页内链调取规则

### 12.1 固定调取来源

每次生成最终发布包前，必须调取并抓取以下 URL：
```
{brand_site_url}/category/blog/
```
作为默认站内内链候选来源。

### 12.2 筛选规则

内链筛选必须结合当前文章：
- 主关键词
- 搜索意图
- 文章集群位置
- 读者阶段
- 正文中可自然承接的上下文

**优先选择：**
- 对当前概念提供更基础解释的文章
- 对当前问题提供更深入诊断的文章
- 对当前决策提供下一步行动的文章
- 与当前文章属于同一主题集群但搜索意图不同的文章

**禁止选择：**
- 与当前文章争夺同一主关键词或同一搜索意图的文章
- 主题高度重复、可能造成 cannibalization 的文章
- 语义弱相关、只为凑数量而插入的文章
- URL 未验证或可能 404 的文章

### 12.3 嵌入要求

- 最终 HTML 发布包必须把筛选后的内链真实嵌入 `Final article body`，链接必须可点击
- 必须同步列出内链使用说明：锚文本、目标 URL、插入位置、选择原因

### 12.4 失败处理

| 情况 | 行为 |
|------|------|
| 抓取失败 | 明确说明失败原因，要求用户提供可用内链；**不得**静默输出无内链 HTML |
| 抓取成功但无合适内链 | 说明不插入的理由，等待用户确认是否继续 |
| 用户未说明"不加内链" | 最终 HTML 必须包含 **至少 1 条** 真实站内内链 |

---

## 十四、CTA 默认跳转链接规则

### 13.1 默认 CTA URL

```
{brand_site_url}/contact/
```

### 13.2 适用范围

博客发布包中的咨询型 CTA，包括但不限于：
- Talk to us
- Connect with us
- Talk to us / Get a demo / Contact sales
- Contact us
- Talk to an SMS expert

### 13.3 优先级

| 条件 | CTA URL |
|------|---------|
| 用户任务中提供明确 CTA URL | 使用用户提供的 URL |
| 用户未提供 | 使用 `{brand_site_url}/contact/` |
| 不允许 | href="#" 等无意义默认值 |

### 13.4 适用位置

- Final article body 中的 CTA Button
- 发布包 CTA 字段

### 13.5 文案规则

- CTA 文案可以根据文章语境调整
- 但链接默认保持为 `{brand_site_url}/contact/`，除非用户另行指定
- 发布后自检清单必须包含 CTA URL 检查项
