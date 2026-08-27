# SMSBoosting 博客文章模板使用规范

| 项目 | 内容 |
|---|---|
| 文件名称 | SMSBoosting 博客文章模板使用规范 |
| 适用对象 | SMSBoosting 官网博客文章 |
| 适用平台 | WordPress + Elementor Single Post Template |
| 模板体系 | Elementor 页面级模板 + HTML 正文内容模板 |
| 当前状态 | 已确认并投入使用 |
| 主要用途 | 统一博客文章页面结构、正文视觉、目录规则、FAQ、References 与正文增强模块样式 |

---

## 1. 模板体系总览

SMSBoosting 博客文章采用两层模板体系：

| 层级 | 负责内容 |
|---|---|
| Elementor Single Post 模板 | 页面级结构、文章标题区、文章信息、左侧目录、正文输出区、相关文章、文章导航、分享按钮、整体页面布局 |
| HTML 正文模板 | 正文段落、H2 / H3、列表、表格、图片、CTA、FAQ、References、正文内部增强模块 |

整体原则：

> Elementor 模板负责页面骨架，HTML 模板负责正文内容增强。

---

# 一、Elementor Single Post 模板规范

## 1.1 模板定位

Elementor Single Post 模板是 SMSBoosting 博客文章的统一页面级模板，用于承接 WordPress Post 类型文章的前台展示。

| 项目 | 内容 |
|---|---|
| 模板类型 | Single Post Template |
| 应用范围 | Posts |
| Display Conditions | Include → Posts → All |
| 使用方式 | 新建或发布博客文章时自动套用 |
| 旧模板状态 | 保留为备份模板 |

---

## 1.2 Elementor 模板整体结构

```text
Single Post Template

1. 顶部文章信息区
   - Blog / Category 标签
   - Post Title
   - Post Info

2. 正文阅读区
   - 左侧：Table of Contents
   - 右侧：Post Content

3. 文章尾部区
   - Related Posts
   - Post Navigation
   - Share Buttons
```

---

## 1.3 顶部文章信息区

### 1.3.1 Blog / Category 标签

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor 模板 |
| 内容来源 | WordPress 分类 / 标签 |
| 字体 | Georgia 或系统字体 |
| 字号 | 12px–14px |
| 字重 | 500–600 |
| 文字颜色 | `#3F5242` |
| 背景色 | `#EEF3EC` |
| 边框色 | `#C9D5C5` |
| 圆角 | 999px |
| 内边距 | 6px 12px |
| 位置 | H1 标题上方 |
| 视觉角色 | 文章分类识别与轻量标签提示 |

### 1.3.2 Post Title / H1

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor Post Title |
| 内容来源 | WordPress 文章标题 |
| 字体 | Georgia |
| 备用字体 | `"Times New Roman", serif` |
| 颜色 | `#132019` |
| 字重 | 400 |
| 桌面端字号 | 78px–92px |
| 推荐桌面字号 | 86px |
| 平板端字号 | 56px–68px |
| 手机端字号 | 42px–48px |
| 行高 | 0.95–1.02 |
| 推荐行高 | 0.98 |
| 字间距 | -2px 到 -4px |
| 推荐字间距 | -3px |
| 对齐方式 | Left |
| 最大宽度 | 1000px–1120px |
| 视觉风格 | 大标题、低装饰、editorial blog 风格 |

### 1.3.3 Post Info

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor Post Info |
| 显示内容 | 发布日期、作者信息 |
| 字体 | Georgia 或系统字体 |
| 字号 | 13px–15px |
| 颜色 | `#687268` |
| 字重 | 400 |
| 行高 | 1.4–1.6 |
| 与 H1 间距 | 18px–28px |
| 与正文阅读区间距 | 40px–60px |
| 视觉角色 | 文章辅助信息展示 |

---

## 1.4 正文阅读区

### 1.4.1 阅读区布局

| 项目 | 内容 |
|---|---|
| 布局形式 | 左侧目录 + 右侧正文 |
| 外层布局 | Flexbox |
| 左侧内容 | Table of Contents |
| 右侧内容 | Post Content |
| 左侧目录宽度 | 240px–280px |
| 右侧正文宽度 | 占据剩余阅读空间 |
| 左右间距 | 40px–56px |
| 桌面端 | 左目录 + 右正文 |
| 平板端 | 上下排列或简化结构 |
| 手机端 | 目录隐藏或折叠展示 |

### 1.4.2 阅读区 class 命名

| 元素 | CSS Class |
|---|---|
| 阅读区外层 | `sms-post-grid` |
| 左侧目录容器 | `sms-toc-column` |
| 右侧正文容器 | `sms-content-column` |

### 1.4.3 左侧 Table of Contents 目录

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor Table of Contents |
| 目录位置 | 左侧 |
| 固定方式 | Sticky |
| Sticky Offset | 80px–100px |
| 读取标题层级 | H2 |
| 目录宽度 | 240px–280px |
| 目录内容滚动 | 目录内部滚动 |
| 目录标题 | Table of Contents |
| 目录标题字号 | 16px–18px |
| 目录项字号 | 14px–16px |
| 目录项行高 | 1.4–1.6 |
| 普通文字颜色 | `#39433C` |
| Hover 背景色 | `#EEF3EC` |
| Hover 文字色 | `#132019` |
| Hover 圆角 | 8px |
| Hover 效果 | 背景色变化 |
| 当前目录项视觉 | 浅莫兰迪绿色背景 |

### 1.4.4 Post Content 模块

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor Post Content |
| 内容来源 | WordPress 文章正文 |
| 所在位置 | 右侧正文区域 |
| 宽度 | 100% |
| 背景 | 透明 |
| 内容承接 | `.sms-blog-content` 正文 HTML |

---

## 1.5 文章尾部区

### 1.5.1 Related Posts

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor Posts Widget |
| 模块标题 | Related Posts |
| Query 类型 | Related |
| Related By | Category / Tags |
| 排除规则 | Current Post |
| 显示数量 | 2 篇 |
| Columns | 2 |
| 图片比例 | 16:9 |
| 显示内容 | Featured Image、文章标题、日期 |
| 模块标题字体 | Georgia |
| 模块标题颜色 | `#132019` |
| 模块标题字号 | 48px–64px |
| 模块标题字重 | 400–500 |
| 视觉角色 | 文章尾部站内延伸阅读 |

### 1.5.2 Post Navigation

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor Post Navigation |
| 显示内容 | Previous Post / Next Post |
| 位置 | Related Posts 附近 |
| 用途 | 承接站内文章浏览路径 |

### 1.5.3 Share Buttons

| 项目 | 内容 |
|---|---|
| 模块来源 | Elementor Share Buttons |
| 显示位置 | 文章尾部区域 |
| 用途 | 支持文章分享 |
| 风格 | 与莫兰迪绿色系统保持一致 |

---

## 1.6 Elementor 模板样式资产

### 1.6.1 左侧目录与右侧正文布局 CSS

```css
.sms-post-grid {
  display: flex;
  align-items: flex-start;
  gap: 40px;
  width: 100%;
}

.sms-toc-column {
  flex: 0 0 240px;
  max-width: 280px;
  position: sticky;
  top: 100px;
  align-self: flex-start;
  z-index: 20;
}

.sms-content-column {
  flex: 1 1 auto;
  min-width: 0;
  width: 100%;
}

.sms-content-column .elementor-widget-theme-post-content,
.sms-content-column .elementor-widget-post-content,
.sms-content-column .elementor-widget-container,
.sms-content-column .sms-blog-content {
  width: 100%;
  max-width: none;
  min-width: 0;
}
```

### 1.6.2 目录 hover 样式

```css
.sms-post-grid .elementor-toc__list-item-text,
.sms-post-grid .elementor-toc__list-item-text a,
.sms-post-grid .elementor-toc__body a {
  text-decoration: none;
  border-bottom: none;
  box-shadow: none;
  display: inline-block;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.sms-post-grid .elementor-toc__list-item-text:hover,
.sms-post-grid .elementor-toc__list-item-text a:hover,
.sms-post-grid .elementor-toc__body a:hover {
  background: #EEF3EC;
  color: #132019;
  text-decoration: none;
  border-bottom: none;
  box-shadow: none;
}
```

---

# 二、HTML 正文模板规范

## 2.1 HTML 模板定位

HTML 正文模板负责文章正文内部内容与正文增强模块。

HTML 内容通过 WordPress Post Content 输出，并由 Elementor Single Post 模板承接前台展示。

---

## 2.2 HTML 正文外层结构

每篇文章正文统一使用以下外层容器：

```html
<div class="sms-blog-content">
  ...
</div>
```

`.sms-blog-content` 用于限定正文样式作用范围。

---

## 2.3 HTML 模板包含的内容类型

| 内容类型 | 说明 |
|---|---|
| 正文段落 | 文章主体文本 |
| H2 | 正文主章节 |
| H3 | 正文次级小节 |
| 有序列表 | 步骤、顺序、流程 |
| 无序列表 | 要点、检查项、原因说明 |
| 表格 | 对比、参数、规则、判断标准 |
| 图片 | 正文配图 |
| 图片说明 | 图片补充说明 |
| CTA 模块 | 正文内部转化模块 |
| FAQ 模块 | 折叠问答模块 |
| References 模块 | 小字号参考资料卡片模块 |
| 正文增强模块 | 卡片、提示框、流程、对比、判断矩阵等 |

---

# 三、HTML 正文基础视觉规范

## 3.1 颜色系统

| 颜色角色 | 色值 |
|---|---|
| 主绿色 | `#5D765F` |
| Hover 深绿色 | `#4D6350` |
| 深绿色 | `#3F5242` |
| 浅绿色背景 | `#EEF3EC` |
| 更浅绿色背景 | `#F5F8F3` |
| 主标题色 | `#132019` |
| 次级标题色 | `#213027` |
| 正文色 | `#39433C` |
| 辅助文字色 | `#687268` |
| Section 背景 | `#FBFCF8` |
| FAQ 问题背景 | `#F1F5EF` |
| FAQ 答案背景 | `#F6F8F3` |
| 普通边框色 | `#DFE2DA` |
| 浅绿边框色 | `#C9D5C5` |
| References 背景 | `#F1F3ED` |

## 3.2 正文字体

| 项目 | 内容 |
|---|---|
| 字体 | Georgia |
| 备用字体 | `"Times New Roman", serif` |
| 正文颜色 | `#39433C` |
| 字重 | 400 |
| 字体风格 | 编辑感、阅读感、低装饰 |

## 3.3 正文段落

| 项目 | 桌面端 |
|---|---|
| 字号 | 19px |
| 行高 | 1.74 |
| 段落下间距 | 20px |
| 字重 | 400 |
| 颜色 | `#39433C` |

### 首段样式

| 项目 | 内容 |
|---|---|
| 字号 | 20px–21px |
| 行高 | 1.6–1.65 |
| 颜色 | `#2D3831` |

### 移动端正文

| 项目 | 内容 |
|---|---|
| 正文字号 | 17px |
| 首段字号 | 18px |
| 行高 | 1.65–1.72 |

---

# 四、HTML 标题层级规范

## 4.1 H2 主章节标题

| 项目 | 内容 |
|---|---|
| 用途 | 正文主章节 |
| 字体 | Georgia |
| 字号 | `clamp(32px, 3vw, 44px)` |
| 字重 | 500 |
| 行高 | 1.12 |
| 字间距 | -0.035em |
| 颜色 | `#132019` |
| 上方间距 | 78px |
| 下方间距 | 32px |
| 背景 | 透明 |
| 样式 | 纯文字标题 |
| 目录关系 | Elementor Table of Contents 默认读取对象 |

## 4.2 H3 次级标题

| 项目 | 内容 |
|---|---|
| 用途 | 正文次级小节 |
| 字体 | Georgia |
| 字号 | `clamp(22px, 1.8vw, 27px)` |
| 字重 | 500 |
| 行高 | 1.28 |
| 字间距 | -0.012em |
| 颜色 | `#213027` |
| 上方间距 | 48px |
| 下方间距 | 16px |
| 背景 | 透明 |
| 样式 | 纯文字标题 |

## 4.3 移动端标题

| 标题 | 字号 | 上方间距 | 下方间距 |
|---|---:|---:|---:|
| H2 | 31px | 58px | 24px |
| H3 | 23px | 38px | 16px |

---

# 五、HTML 列表规范

## 5.1 列表容器

| 项目 | 内容 |
|---|---|
| 背景色 | `#EEF3EC` |
| 边框 | `1px solid #C9D5C5` |
| 圆角 | 18px |
| 内边距 | 22px 26px 22px 36px |
| 外边距 | 22px 0 32px |

## 5.2 列表文字

| 项目 | 内容 |
|---|---|
| 字号 | 19px |
| 行高 | 1.62 |
| 颜色 | `#39433C` |
| marker 颜色 | `#3F5242` |
| marker 字重 | 700 |
| 单项间距 | 9px |

---

# 六、HTML FAQ 模块规范

## 6.1 FAQ 模块结构

FAQ 使用原生 HTML 折叠结构：

```html
<section class="faq-section">
  <h2>FAQ</h2>

  <div class="faq-list">
    <details class="faq-item" open>
      <summary>Question</summary>
      <div class="faq-answer">
        <p>Answer...</p>
      </div>
    </details>
  </div>
</section>
```

## 6.2 FAQ 外层样式

| 项目 | 内容 |
|---|---|
| 背景 | `#FBFCF8` |
| 边框 | `1px solid #DFE2DA` |
| 圆角 | 24px |
| 内边距 | 34px |
| 上方间距 | 76px |

## 6.3 FAQ 标题

| 项目 | 内容 |
|---|---|
| 字体 | Georgia |
| 字号 | `clamp(30px, 2.8vw, 40px)` |
| 字重 | 500 |
| 行高 | 1.14 |
| 字间距 | -0.03em |
| 颜色 | `#132019` |
| 下方间距 | 26px |

## 6.4 FAQ 问题卡片

| 项目 | 内容 |
|---|---|
| 背景 | `#F1F5EF` |
| 边框 | `1px solid #C9D5C5` |
| 圆角 | 18px |
| 间距 | 14px |
| 问题字号 | 19px |
| 问题行高 | 1.35 |
| 问题字重 | 500 |
| 问题颜色 | `#132019` |
| 内边距 | 18px 48px 18px 20px |

## 6.5 FAQ 答案区域

| 项目 | 内容 |
|---|---|
| 背景 | `#F6F8F3` |
| 顶部分割线 | `1px solid #C9D5C5` |
| 内边距 | 18px 20px 20px |
| 答案字号 | 17px |
| 答案行高 | 1.64 |
| 答案颜色 | `#39433C` |

---

# 七、HTML References 模块规范

## 7.1 References 模块结构

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

## 7.2 References 外层样式

| 项目 | 内容 |
|---|---|
| 背景 | `#FBFCF8` |
| 边框 | `1px solid #DFE2DA` |
| 圆角 | 24px |
| 内边距 | 34px |
| 上方间距 | 34px 或 76px |

## 7.3 References 标题

| 项目 | 内容 |
|---|---|
| 字体 | Georgia |
| 字号 | `clamp(30px, 2.8vw, 40px)` |
| 字重 | 500 |
| 行高 | 1.14 |
| 颜色 | `#132019` |
| 下方间距 | 26px |

## 7.4 Reference 条目卡片

| 项目 | 内容 |
|---|---|
| 背景 | `#F1F3ED` |
| 边框 | `1px solid #DFE2DA` |
| 圆角 | 14px |
| 内边距 | 14px 16px |
| 条目间距 | 12px |
| 布局 | 编号 + 正文 |

## 7.5 Reference 编号

| 项目 | 内容 |
|---|---|
| 字号 | 14px |
| 字重 | 600 |
| 颜色 | `#3F5242` |
| 行高 | 1.55 |

## 7.6 Reference 正文

| 项目 | 内容 |
|---|---|
| 字号 | 14px |
| 行高 | 1.58 |
| 颜色 | `#687268` |
| 加粗文字颜色 | `#213027` |

---

# 八、HTML 图片模块规范

## 8.1 图片基础样式

| 项目 | 内容 |
|---|---|
| 图片宽度 | 100% |
| 图片圆角 | 18px–24px |
| 上方间距 | 40px–56px |
| 下方间距 | 40px–56px |
| 图片说明字号 | 13px–14px |
| 图片说明颜色 | `#687268` |

## 8.2 图片内容规则

| 项目 | 内容 |
|---|---|
| alt 文本 | 每张图片保留 |
| 图片位置 | 按正文阅读节奏插入 |
| 图片角色 | 解释、补充、总结或场景化说明 |

---

# 九、HTML CTA 模块规范

## 9.1 CTA 模块定位

CTA 作为正文内部的轻转化模块，用于承接教育型内容后的咨询、诊断、供应商评估或技术支持需求。

## 9.2 CTA 样式

| 项目 | 内容 |
|---|---|
| 背景 | `#EEF3EC` 或 `#F6F8F3` |
| 边框 | `1px solid #C9D5C5` |
| 圆角 | 22px–24px |
| 内边距 | 28px–36px |
| 标题字号 | 26px–34px |
| 正文字号 | 17px–18px |
| 按钮背景 | `#3F5242` |
| 按钮文字 | `#FFFFFF` |
| 按钮圆角 | 999px |
| 视觉风格 | Soft Consult |

---

# 十、HTML 固定模块与可变化模块规则

## 10.1 HTML 模板分层原则

SMSBoosting 博客正文 HTML 采用 **基础视觉统一 + 正文模块可变化** 的模板策略。

正文 HTML 的基础层保持统一，用于保证博客文章的品牌一致性、阅读稳定性和长期维护效率。正文 HTML 的模块层根据文章类型、搜索意图和内容表达需要进行组合变化，用于增强每篇文章的阅读节奏、信息层级和转化承接能力。

---

## 10.2 HTML 固定模块

HTML 固定模块指所有博客文章正文中保持一致的基础视觉与结构规则。

| 固定模块 | 固定内容 |
|---|---|
| 正文外层容器 | `.sms-blog-content` |
| 正文字体 | Georgia |
| 正文颜色 | `#39433C` |
| H2 基础样式 | 纯文字主章节标题 |
| H3 基础样式 | 纯文字次级标题 |
| FAQ 基础结构 | `<details>` / `<summary>` 折叠卡片 |
| References 基础结构 | 小字号卡片列表 |
| 列表基础样式 | 浅绿色背景 + 浅绿边框 |
| 莫兰迪绿色系统 | 主绿色、深绿色、浅绿背景、边框色统一 |
| CSS 作用域 | `.sms-blog-content` |

---

## 10.3 HTML 可变化模块

HTML 可变化模块指根据文章类型、搜索意图、内容结构和转化目标进行组合变化的正文增强模块。

这些模块共享 SMSBoosting 的字体、颜色、圆角、边框和阅读风格，但模块类型、排列顺序、信息密度和展示方式可根据文章需要调整。

### 10.3.1 Definition Card

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 强化核心概念、定义、术语解释 |
| 适用文章 | What / Why / Definition 类文章 |
| 常见位置 | 引言后、核心概念首次出现处 |
| 视觉风格 | 浅色卡片、低饱和绿色强调、正文同系字体 |
| 内容结构 | 标题 + 简短解释 + 可选补充说明 |

### 10.3.2 Key Takeaway Card

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 提炼阶段性结论或文章核心判断 |
| 适用文章 | 教育型文章、解释型文章、总结型文章 |
| 常见位置 | 引言后、H2 小节后、文章中段总结处 |
| 视觉风格 | 浅绿色背景或浅灰绿色背景 |
| 内容结构 | Takeaway 标题 + 1–3 条重点 |

### 10.3.3 Checklist Block

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 展示检查项、准备项、排查项 |
| 适用文章 | How-to、diagnostic、troubleshooting 类文章 |
| 常见位置 | 操作步骤前、排查路径中、结论前 |
| 视觉风格 | 浅绿色列表卡片 |
| 内容结构 | Checklist 标题 + 多条检查项 |

### 10.3.4 Step Cards

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 展示顺序动作、流程路径、操作步骤 |
| 适用文章 | How-to、implementation、workflow 类文章 |
| 常见位置 | 操作指南主体部分 |
| 视觉风格 | 分步骤卡片、编号突出、低饱和绿色辅助 |
| 内容结构 | Step 编号 + 标题 + 简短说明 |

### 10.3.5 Evidence Card

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 展示排查证据、支持升级信息、判断依据 |
| 适用文章 | Delivery issue、filtering、diagnostic 类文章 |
| 常见位置 | 问题排查章节、升级判断章节 |
| 视觉风格 | 卡片式证据清单 |
| 内容结构 | Evidence 标题 + 证据项 + 说明 |

### 10.3.6 Risk Box

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 提示风险、误判点、常见错误 |
| 适用文章 | 合规、过滤、送达失败、供应商选择类文章 |
| 常见位置 | 风险说明段落后 |
| 视觉风格 | 柔和提示框，保持低饱和色系 |
| 内容结构 | Risk 标题 + 风险说明 + 可选处理方向 |

### 10.3.7 Comparison Table

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 对比概念、方案、类型、服务能力 |
| 适用文章 | Comparison / Decision 类文章 |
| 常见位置 | 对比型 H2 章节中 |
| 视觉风格 | 简洁表格、浅边框、重点项绿色强调 |
| 内容结构 | 对比维度 + 对象 A + 对象 B + 判断说明 |

### 10.3.8 Decision Matrix

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 帮助读者做选择或判断 |
| 适用文章 | Provider selection、strategy、comparison 类文章 |
| 常见位置 | 文章中后段、购买旅程承接处 |
| 视觉风格 | 表格或卡片矩阵 |
| 内容结构 | 条件 / 场景 / 推荐方向 |

### 10.3.9 Scenario Cards

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 展示业务场景、使用案例、应用路径 |
| 适用文章 | Use case、industry、solution 类文章 |
| 常见位置 | 场景解释章节 |
| 视觉风格 | 多卡片并列或上下排列 |
| 内容结构 | 场景名称 + 业务问题 + 对应短信能力 |

### 10.3.10 Process Flow Block

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 展示流程、路径、阶段关系 |
| 适用文章 | API、delivery path、diagnostic workflow 类文章 |
| 常见位置 | 流程说明章节 |
| 视觉风格 | 线性流程、步骤卡片或轻量箭头 |
| 内容结构 | 阶段 1 → 阶段 2 → 阶段 3 |

### 10.3.11 Internal Link Card

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 承接集群内链、引导读者继续阅读 |
| 适用文章 | 所有博客文章 |
| 常见位置 | 相关概念出现处、章节结尾、正文中后段 |
| 视觉风格 | 轻量卡片、文本链接突出 |
| 内容结构 | Read next 标题 + 相关文章锚文本 + 简短说明 |

### 10.3.12 CTA Block

| 项目 | 使用规则 |
|---|---|
| 模块用途 | 承接咨询、诊断、供应商评估、技术支持需求 |
| 适用文章 | 商业意图、诊断、供应商选择、API 实现类文章 |
| 常见位置 | 文章中后段或结尾前 |
| 视觉风格 | Soft Consult 风格 |
| 内容结构 | CTA 标题 + 简短说明 + 按钮 |

---

## 10.4 不同文章类型的模块组合规则

### 10.4.1 概念解释型文章

| 项目 | 模块组合 |
|---|---|
| 适用文章 | What / Why / Definition |
| 常用模块 | Definition Card、Key Takeaway Card、Factor Cards、Misconception Block、FAQ、References |
| 视觉节奏 | 定义清晰、层级稳定、阅读压力低 |

### 10.4.2 诊断排查型文章

| 项目 | 模块组合 |
|---|---|
| 适用文章 | Why / Troubleshooting / Diagnostic |
| 常用模块 | Step Cards、Checklist Block、Evidence Card、Risk Box、Escalation Criteria Box、FAQ、References |
| 视觉节奏 | 路径明确、证据优先、步骤清楚 |

### 10.4.3 对比决策型文章

| 项目 | 模块组合 |
|---|---|
| 适用文章 | Comparison / Decision / Provider Selection |
| 常用模块 | Comparison Table、Decision Matrix、Pros / Cons Cards、Scenario Cards、Selection Checklist、FAQ、References |
| 视觉节奏 | 对比明确、选择依据清楚、购买判断顺畅 |

### 10.4.4 操作指南型文章

| 项目 | 模块组合 |
|---|---|
| 适用文章 | How-to / Checklist / Implementation |
| 常用模块 | Step Cards、Checklist Block、Process Flow Block、Do / Don’t Block、CTA、FAQ、References |
| 视觉节奏 | 操作顺序清晰、执行路径明确 |

### 10.4.5 场景应用型文章

| 项目 | 模块组合 |
|---|---|
| 适用文章 | Use Case / Industry Scenario / Application |
| 常用模块 | Scenario Cards、Process Flow Block、Key Takeaway Card、Internal Link Card、CTA、FAQ、References |
| 视觉节奏 | 场景先行、业务问题明确、能力承接自然 |

---

## 10.5 可变化模块的统一视觉边界

| 项目 | 统一规则 |
|---|---|
| 字体 | Georgia |
| 主标题色 | `#132019` |
| 正文色 | `#39433C` |
| 辅助文字色 | `#687268` |
| 主绿色 | `#5D765F` |
| 深绿色 | `#3F5242` |
| 浅绿色背景 | `#EEF3EC` / `#F6F8F3` |
| 边框色 | `#DFE2DA` / `#C9D5C5` |
| 圆角 | 14px–24px |
| 卡片内边距 | 20px–36px |
| 模块间距 | 40px–76px |
| 视觉风格 | 低饱和、干净、商务、editorial |

---

# 十一、HTML 基础结构示例

```html
<div class="sms-blog-content">

  <p>Opening paragraph...</p>

  <h2>Section Title</h2>
  <p>Section content...</p>

  <h3>Subsection Title</h3>
  <p>Subsection content...</p>

  <ul>
    <li>List item</li>
    <li>List item</li>
  </ul>

  <section class="faq-section">
    <h2>FAQ</h2>

    <div class="faq-list">
      <details class="faq-item" open>
        <summary>Question</summary>
        <div class="faq-answer">
          <p>Answer...</p>
        </div>
      </details>

      <details class="faq-item">
        <summary>Question</summary>
        <div class="faq-answer">
          <p>Answer...</p>
        </div>
      </details>
    </div>
  </section>

  <section class="references-section">
    <h2>References</h2>

    <div class="references-list">
      <div class="reference-item">
        <span class="reference-number">[1]</span>
        <p>Reference description...</p>
      </div>
    </div>
  </section>

</div>
```

---

# 十二、CSS 作用域规则

正文 HTML 的 CSS 使用 `.sms-blog-content` 作为统一作用域。

示例：

```css
.sms-blog-content h2 {}
.sms-blog-content h3 {}
.sms-blog-content p {}
.sms-blog-content .faq-section {}
.sms-blog-content .references-section {}
```

Elementor 模板中的目录、标题、Related Posts、Post Navigation 和 Share Buttons 使用 Elementor 模板层样式与对应 class 管理。

---

# 十三、发布使用方式

## 13.1 新建文章流程

| 步骤 | 内容 |
|---|---|
| 1 | 新建 WordPress Post |
| 2 | 填写文章标题 |
| 3 | 设置分类 |
| 4 | 设置 Featured Image |
| 5 | 粘贴 `.sms-blog-content` 正文 HTML |
| 6 | 设置 Yoast SEO title / meta description / slug |
| 7 | 预览前台 |
| 8 | 发布文章 |

## 13.2 前台检查项

| 检查项 | 内容 |
|---|---|
| H1 | 使用 Elementor 模板标题样式 |
| 日期 / 作者 | 正常显示 |
| 左侧目录 | 自动读取 H2 |
| 正文 | 使用 `.sms-blog-content` 样式 |
| FAQ | 可展开 / 收起 |
| References | 小字号卡片显示 |
| Related Posts | 显示 2 篇相关文章 |
| 移动端 | 正文正常阅读 |
