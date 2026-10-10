---
name: html-report
description: |
  生成美观的简历筛选 HTML 报告。接受 resume-screener 输出的 screening_results.json，渲染候选人排名、5 维度评分进度条、评分依据、行动建议。

  **本 Skill 不是工作流入口**。通用智能体应只通过
  [boss-hr-auto](../boss-hr-auto/SKILL.md) → 统一 CLI `boss-hr report` 调用。
  本文档保留作为：HTML 报告渲染实现参考 / 模板说明 / 内部脚本接口文档。

  **唯一方案**：通用 schema 渲染 + LLM 自由填写的 highlights/concerns/advice 直接展示。任意岗位通用。
---

# HTML 报告生成（统一方案）

## 设计核心

- **通用 schema**：接受 `resume-screener/scripts/score_resumes.py` 输出的 `screening_results.json`，**任意岗位都能用**
- **LLM 自由填写**：candidates[].highlights / concerns / actions[].{background, action, strengths} 由 LLM 决定内容，脚本只负责渲染
- **字段鲁棒**：所有字段 `.get()` 处理，缺失自动跳过
- **视觉风格**：黑蓝渐变 header + 玻璃质感 meta-item + 三色 stat-card 配色

---

## 核心不变量（不要修改）

| 项 | 值 |
|----|----|
| 输入文件 | `screening_results.json`（由 score_resumes.py 产出） |
| 输出文件 | `*.html`（自包含单文件，无外部依赖） |
| 字体栈 | Inter, "PingFang SC", "Microsoft YaHei" |
| 主色（header） | `linear-gradient(135deg, #1a1a2e, #16213e, #0f3460)` |
| 背景色 | `#f5f7fa` |
| 卡片圆角 | `border-radius: 12px` |
| Tier 颜色 | 推荐 #059669（绿）/ 待定 #d97706（黄）/ 不推荐 #dc2626（红） |
| 进度条颜色 | ≥70% 绿 / 50-69% 黄 / <50% 红 |

---

## 工具脚本

### `scripts/generate_html_report.py`（**唯一**渲染脚本）

**工具函数**（agent 可直接 import）：

| 函数 | 作用 |
|------|------|
| `render(data: dict) → str` | 输入 screening_results.json 数据，输出 HTML 字符串 |
| `bar_color(pct) → str` | 根据百分比返回进度条颜色（绿/黄/红） |
| `tier_badge(tier) → str` | 根据 tier 返回徽章 HTML |
| `render_candidate(c, labels, rank) → str` | 渲染单个候选人卡片 |
| `render_action(name, score, body) → str` | 渲染单个行动建议行 |

**CLI**：

```bash
python generate_html_report.py \
  --input <screening_results.json> \
  --output <report.html> \
  --job-name "<岗位名>" \
  --encrypt-job-id "<BOSS 的 encryptJobId>" \
  --run-id <run_id>
```

> 🚨 **新接口必传 `--encrypt-job-id`**：与 Step 1/2/3 保持一致。也可以设 env `BOSS_HR_ENCRYPT_JOB_ID` 作为 fallback。
> 兼容模式：如果不传，脚本会从 `--input` 路径里反推 `job_name`（旧中文目录）作为兜底，但**新设计必须显式传**，避免与新 job 混目录。

### `templates/report.html`（HTML 模板）

Jinja2 风格模板占位符。**当前未使用**（脚本直接生成自包含 HTML），保留作为参考。

---

## 完整工作流

```
boss-recommend-downloader/scripts/run_all.py
    list + download 串起来
    → 输出 runs/<run_id>/process/{recommend_geek_ids,new_resumes,failed_resumes,run_summary}.json
    ↓
resume-screener/scripts/score_resumes.py
    LLM 评 4 维度（exp/skill/proj/major）
    + school_tier 强制覆盖 edu
    + 公式重算 total
    + 判定 tier
    → 输出 runs/<run_id>/process/screening_results.json
    ↓
html-report/scripts/generate_html_report.py
    读取 screening_results.json
    → 输出 runs/<run_id>/<run_id>_<岗位名>_简历筛选报告.html（自包含）
        ↑ 文件名含 run_id，永不覆盖历史报告
        ↑ 头部展示 run-badge：🆔 run_id: <run_id> | 🕐 生成时间: ...
    ↓
preview_url 在 IDE 内置浏览器打开
```

## 工作区路径约定（新设计 · 2026-07-29+）

**所有数据统一存放在 `~/Desktop/boss-hr-output/<encryptJobId>/` 下**，**目录名直接用 BOSS 的 `encryptJobId`**（不再用中文岗位名）。`job_name` 仅作为 `jobs.json` 里的可读元数据。

```
~/Desktop/boss-hr-output/
├── jobs.json                               # JobRegistry：encryptJobId → {name, company}
└── <encryptJobId>/
    ├── state/                              # 跨 run 保留
    └── runs/<run_id>/                      # 一次筛选任务
        ├── <run_id>_screening_report.html  ← 本 skill 输出
        └── process/
            ├── screening_results.json      ← 本 skill 读取
            └── ...
```

> **路径选择集中在 `shared/output_manager.JobOutputManager`**——CLI 脚本只接收并透传 `--encrypt-job-id`，不参与路径拼接。

| Step | Skill | 脚本 | 输出文件 |
|:----:|-------|------|----------|
| 1 | `boss-job-detail` | `boss_jd.py` | `runs/<run_id>/process/job_detail.json` |
| 2B | `boss-recommend-downloader` | `run_all.py` | `runs/<run_id>/process/{recommend_geek_ids,new_resumes,failed_resumes,run_summary}.json` |
| 3 | `resume-screener` | LLM agent | `runs/<run_id>/process/_llm_scores.json` |
| 3 | `resume-screener` | `score_resumes.py` | `runs/<run_id>/process/screening_results.json` |
| 4 | `html-report` | `generate_html_report.py` | `runs/<run_id>/<run_id>_<岗位名>_简历筛选报告.html` |

> 上游脚本（Step 1 / 2）已自动写入工作区，下游脚本（Step 3 / 4）通过 `--input/--output` 读取工作区。
>
> `JobOutputManager` 提供的标准路径属性：`jd_path` / `recommend_geek_ids_path` / `new_resumes_path` / `screening_results_path` / `report_path` / `run_summary_path`。
>
> **同一 run 必须传同一个 `--run-id`** 给所有脚本，产物才落在同一个 `runs/<run_id>/`。

---

## 输入 schema（screening_results.json）

**必填字段**（缺失会报错）：

```json
{
  "job_name": "机械工程师",
  "summary": {"total": 32, "recommend": 0, "pending": 2, "reject": 30},
  "candidates": [
    {
      "rank": 1,
      "name": "候选人丙",
      "tier": "待定",
      "total": 69.8,
      "dimensions": [
        {"pct": 62, "weighted": 15.5, "weight": 25, "reason": "二本公办（school_tier 查询：信阳农林学院）"},
        {"pct": 80, "weighted": 24.0, "weight": 30, "reason": "..."}
      ]
    }
  ]
}
```

**可选字段**（缺失自动跳过对应渲染块）：

| 字段 | 渲染位置 |
|------|----------|
| `meta.title` / `meta.subtitle` | header 标题/副标题 |
| `meta.job.{company,location,salary,experience_required,degree_required}` | meta-grid 卡片 |
| `meta.type_judgment.{type,reason}` | 元信息栏（岗位类型） |
| `meta.core_requirements` | 核心要求列表 |
| `dimension_labels` | 进度条维度名（默认 ["学历","工作经验","专业技能","项目经历","专业匹配"]） |
| `candidates[].school` | 候选人卡片学校 |
| `candidates[].work_years` | 候选人卡片工作年限 |
| `candidates[].current_role` | 候选人卡片当前岗位 |
| `candidates[].hard_pass` / `hard_reason` | 硬门槛标签（一般不出现） |
| `candidates[].dimensions[].reason` | 评分依据列表 |
| `candidates[].highlights` | 候选人亮点列表 |
| `candidates[].concerns` | 候选人顾虑列表 |
| `actions.recommend[]` | 推荐面试清单 |
| `actions.pending[]` | 待沟通确认清单 |
| `actions.reject[]` | 不推荐清单 |

---

## 视觉规范

### 排版结构（5 段式）

1. **Header** — 渐变色（`#1a1a2e → #16213e → #0f3460`），标题 + subtitle + meta-grid（岗位名称/薪资/地点/候选人总数）
2. **筛选总览** — 4 张 stat-card（蓝/绿/黄/红），分别显示总数/推荐/待定/不推荐
3. **排名表格** — 5 维度列（学历 25% / 经验 30% / 技能 25% / 项目 15% / 专业 5%）
4. **候选人详情** — 每候选人一张卡片：基础信息 + 5 维度进度条 + 评分依据列表 + 亮点/顾虑
5. **行动建议** — 三段式（✅ 推荐 / 📌 待沟通 / ❌ 不推荐），每段按 actions 字段渲染

### 配色规则

| 元素 | 颜色 | 触发条件 |
|------|------|----------|
| Tier 徽章 - 推荐 | `#059669` 绿底 | total ≥ 70 |
| Tier 徽章 - 待定 | `#d97706` 黄底 | 60 ≤ total < 70 |
| Tier 徽章 - 不推荐 | `#dc2626` 红底 | total < 60 |
| 进度条 - 高 | `#059669` 绿 | pct ≥ 70 |
| 进度条 - 中 | `#d97706` 黄 | 50 ≤ pct < 70 |
| 进度条 - 低 | `#dc2626` 红 | pct < 50 |

### 容器尺寸

- 最大宽度：1200px
- 卡片 padding：28px
- meta-item padding：12px 16px
- 进度条高度：4px（细圆角）
- 字体标题：28px / 副标题 14px / 标签 11px（大写）/ 数值 16px

---

## 关键设计决策

### 为什么用通用 schema（不用字段硬编码）

- 旧 `generate_report.py` 字段名写死（edu_pct / exp_pct / skill_pct / ...）
- 任何字段增减都要改 HTML 模板，改一处坏一片
- 新通用模板只读 `dimensions[]` 数组，**任意数量、任意顺序的维度都能渲染**
- 加新维度（如"语言能力"）只需在 `WEIGHTS` 加一行 + LLM 评分，HTML 不用动

### 为什么 LLM 自由填写 highlights/concerns/advice（不用 if/else 模板）

- 旧 `generate_report.py` 行动建议用 if/else 模板拼接
- 所有"待定"候选人的建议长得几乎一样（"3 年经验 + 软件能力 + 需确认设计能力"）
- 旧版字段写死会 KeyError 崩溃
- 新方案让 LLM 在评 4 维度时**一起写好** highlights / concerns / advice
- 脚本只负责渲染，不强制格式

### 为什么字段全部 .get() 处理

- screening_results.json 字段可能缺失（不同 JD / 不同 LLM 输出风格不同）
- 缺失字段自动跳过对应渲染块，不报错
- 旧版本字段写死会 KeyError 崩溃

### 为什么 templates/report.html 当前不用

- 旧模板用 Jinja2 占位符，**需要额外的模板引擎依赖**
- 新方案直接 Python f-string 拼字符串，**零依赖**
- templates/ 目录保留作为参考，不删除

---

## CLI 调用示例

```bash
python generate_html_report.py \
    --job-name "结构设计、研发工程师" \
    --encrypt-job-id "DemoJobId000000000000000000001" \
    --run-id "2026-01-01_000000"
    # --input/--output 不传则用默认路径（JobOutputManager 自动拼）
```

输出：

```
HTML 报告已生成: .../DemoJobId000000000000000000001/runs/2026-01-01_000000/2026-01-01_000000_screening_report.html
文件大小: 25314 字节
候选人: 5 人
```

> **关键变化**：输出文件名包含 `run_id`，**永不会覆盖历史报告**。报告头部展示 `run-badge`（🆔 run_id + 🕐 生成时间），方便区分同一岗位的多次筛选结果。
> 若希望脚本自动从 `JobOutputManager.report_path` 拼路径，run_id 不传则使用默认值。

---

## 注意事项

- 输入文件必须是 `resume-screener` 产出的 `screening_results.json`，不要手工构造
- tier 字段值必须是 `推荐` / `待定` / `不推荐` 之一（脚本硬编码匹配）
- dimensions 数组按 `score_resumes.py` 的固定顺序输出：edu / exp / skill / proj / major
- 候选人按 rank 升序展示（rank=1 在最前）
- HTML 是自包含单文件，所有 CSS 内联，无外部依赖，可直接邮件发送或打印
