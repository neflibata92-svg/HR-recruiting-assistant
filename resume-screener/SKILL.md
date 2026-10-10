---
name: resume-screener
description: |
  简历筛选与评分系统的**实现参考**。LLM 评 4 维度最终分（exp/skill/proj/major）+ 脚本查 school_tier 校准 edu + 公式重算 total。

  **本 Skill 不是工作流入口**。通用智能体应只通过
  [boss-hr-auto](../boss-hr-auto/SKILL.md) → 统一 CLI `boss-hr score` 调用。
  本文档保留作为：评分规则参考 / LLM 提示词片段来源 / 算法实现文档。

  **唯一方案**：5 维度 weighted 求和（edu 25% / exp 25% / skill 25% / proj 15% / major 10%），Tier 阈值 ≥70 推荐 / 60-69 待定 / <60 不推荐。
---

# Resume Screener

## 🔁 跨 run 评分去重（脚本自动执行）

`score_resumes.py` 自带去重，**智能体不需要手工过滤已评分候选人**：

- **入口**：按 `job_id:geek_id` 查 `state/scored_state.json`，历史评过的自动跳过
- **出口**：本轮评分结果自动回写 `scored_state.json`
- **逃生门**：`--rescore` 强制重评（换 JD、改评分口径时用）

```bash
# 正常评分（自动跳过历史已评人员）
python score_resumes.py --input _llm_scores.json --output screening_results.json \
  --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "$RUN_ID"
# → ⏭ 跳过 12 位历史已评分候选人：张三、李四...
# 缺 _llm_scores.json → SystemExit(26) + JSON 错误提示

# 换了 JD 要全部重评
python score_resumes.py --input _llm_scores.json --output screening_results.json \
  --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "$RUN_ID" --rescore
```

> 去重按 **geek_id** 而非姓名。BOSS 上「杨先生」「吕女士」这类匿名昵称会重名，
> 脚本对同一姓名维护 ID 列表：**只要还有任一同名候选人未评分就放行**
> （宁可偶尔重复评分，也不把没评过的人误杀）。
>
> 姓名 → geek_id 的映射从 `state/resumes_master.json` 反查，所以
> **`_llm_scores.json` 里的 `name` 必须与简历原始姓名一致**，改写姓名会导致匹配失败（脚本会告警）。

---

## 评分架构

- **LLM 评 4 维度最终分**：`exp / skill / proj / major` 全部由 LLM 真实分析完整简历后给出 0–100 的最终分（已综合考虑年限、对口度、实操深度、复杂度等）
- **脚本只覆盖 1 维度**：用 `scripts/school_tier.py` 查表覆盖 `edu`
- **公式重算**：5 维度 × 权重 = total（按 25/25/25/15/10）
- **Tier 判定**：≥70 推荐 / 60-69 待定 / <60 不推荐
- **通用**：不限岗位（任一 JD 都能用）

> LLM 不输出 `industry_fit` 之类的系数标签。`exp` 分本身已综合考虑对口度，脚本不会再乘任何系数。

---

## 核心不变量

| 项 | 值 |
|----|----|
| 5 维度权重 | edu 25% / exp 25% / skill 25% / proj 15% / major 10% |
| Tier 阈值 | 推荐 ≥70 / 待定 60-69 / 不推荐 <60 |
| 公式 | total = Σ (raw × weight) |
| Tier 名称 | 推荐 / 待定 / 不推荐 |
| 学校分档 | 7 档（C9 / 985 / 211 / 双一流 / 一本公办 / 二本公办 / 民办） |
| 评分主体 | LLM 评 4 维度最终分 + 脚本查 edu（仅此一套） |

---

## 工具脚本

### `scripts/score_resumes.py`

**工具函数**（agent 直接 import 调用）：

| 函数 | 作用 |
|------|------|
| `_extract_school_name(score)` | 智能拆纯校名（优先 `school_name`，兜底从 `school` 按 `/·（(` 拆分） |
| `validate_score(score)` | LLM 评分收尾：用 school_tier 覆盖 edu + 重算 weighted + total + 判定 tier |
| `calc_tier(total)` | ≥70 推荐 / 60-69 待定 / <60 不推荐 |
| `calc_weighted(dims)` | 5 维度 × 权重 |
| `calc_total(weighted)` | 求和 |
| `candidate_to_report(c, rank)` | list 元素 → candidates[] 格式 |
| `build_actions(candidates)` | 生成 actions 三段式（recommend/pending/reject） |
| `build_meta(job_name, job_info)` | 构造报告 meta |

**CLI**：

```bash
python score_resumes.py \
  --input <llm_scores.json> \
  --output <screening_results.json> \
  --job-name "<岗位名>" \
  --encrypt-job-id "<BOSS 的 encryptJobId>" \
  --job-info <JD JSON 字符串> \
  --run-id <run_id>
```

> 🚨 **新接口必传 `--encrypt-job-id`**：工作区目录名 = `encryptJobId`，与 Step 1/2/4 保持一致。也可以设 env `BOSS_HR_ENCRYPT_JOB_ID` 作为 fallback。缺则直接 `ValueError` 退出（严格模式，不静默回退）。

### `scripts/school_tier.py`

```python
from school_tier import lookup
info = lookup("辽宁工业大学")
# → {"tier": "二本公办", "score": 62, "matched": "辽宁工业大学", "fuzzy": False}
info = lookup("江南大学")
# → {"tier": "211", "score": 85, "matched": "江南大学", "fuzzy": False}
```

支持精确匹配 + 模糊匹配（输入校名是表内校的子串或父串时也能命中）。

---

## 完整工作流（2026-07-31 v3：LLM 每评一份立即落盘）

```
# 公共参数（5 步全流程同一个 encryptJobId）
export ENCRYPT_ID="DemoJobId000000000000000000001"
export JOB_NAME="结构设计、研发工程师"
export RUN_ID="2026-01-01_000000"

# 假设已有 runs/<run_id>/process/new_resumes.json（来自 boss-recommend-downloader）

# 0. 简历净化层 —— 把 new_resumes.json 拆成每人一份（2026-07-31 v2）
#    输入：new_resumes.json（动辄几 MB，含 _meta/active_status/空字段等噪声）
#    输出：runs/<run_id>/process/scoring/
#      ├── manifest.json                     # 候选人清单 + status（pending/scored/missing）
#      ├── inputs/candidate_<geek_id>.json   # 净化输入（LLM 读这里）
#      ├── outputs/candidate_<geek_id>.json  # LLM 评分落盘点（每评一个立即写一份）
#      └── _skipped.json                     # 被跳过的简历
#    关键：不改变评分标准，只是把「一坨 JSON」拆成「每人一文件」
python scripts/prepare_scoring_inputs.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"

# 1. LLM agent 读 scoring/manifest.json（拿到候选人清单 + status）
# 2. 对 status="pending" 的候选人循环：
#      a) 读 scoring/inputs/candidate_<geek_id>.json（一份精简简历）
#      b) 调 LLM API 评 4 维度（exp / skill / proj / major），产出评分 object
#      c) **立即落盘**到 scoring/outputs/candidate_<geek_id>.json（单个评分 object）
#      d) 中途崩了下次只需重跑循环里 status="pending" 的那批
# 3. 跑 collect_llm_scores.py：把 outputs/ 合并成 _llm_scores.json（幂等可重跑）
#    - 回写 manifest.status 为 scored / missing / invalid
#    - 不读简历、不做评分，只做文件收集 + 数组拼接
python scripts/collect_llm_scores.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"

# 4. 跑 score_resumes.py 收尾（不读 outputs/，只接 _llm_scores.json）
#    - 用 school_tier 查 edu
#    - 加权 + total + tier 判定
#    - 跨 run 去重（state/scored_state.json）
python score_resumes.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"

# Step 4: 生成 HTML 报告
python html-report/scripts/generate_html_report.py \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id <run_id>
```

### 关键设计点

1. **断点续评**：LLM agent 任何时候崩了，下次只需读 `manifest.json` 挑 `status="pending"` 的继续评，已评的 `scored` 直接跳过。
2. **不污染评分标准**：`score_resumes.py` 的入参 schema 完全不变（仍是 `_llm_scores.json` 数组）；collect_llm_scores.py 只做文件收集 + 拼接，不做任何评分/打分/校准。
3. **校验兜底**：`collect_llm_scores.py` 校验每个 outputs 文件的 schema（必含 `name` / `dims.{exp,skill,proj,major}` 且 0-100），不合法的标 `status="invalid"` 不入数组，错误信息打印在 stdout。
4. **geek_id / job_id 兜底**：如果 LLM 在 outputs 文件里漏写 `geek_id`，collect_llm_scores.py 从 manifest 自动补（避免 score_resumes.py 拒绝评分）。

### 净化层字段规则（白名单 + 必保留）

`prepare_scoring_inputs.py` 从 `new_resumes.json[i]` 净化出 `<index>_<name>.json`，规则：

**只删**：
- `ok` / `age` / `expectation` / `active_status`（接口包装 / 平台状态 / 与评分无关）
- `_meta` 整层（包装字段；`encrypt_geek_id` / `encrypt_job_id` 抽到顶层）
- `work_experience[].performance` / `work_experience[].keywords` / `work_experience[].department`（历年空 / BOSS 内部字段）
- `project_experience[]` 中的全空字段（保留 `name` 作为骨架）
- 空字段（`null` / `""`）在 work_experience / project_experience 内做最小保留（让 LLM 看到"无技能"是证据，不是字段缺失）

**必保留**（评分主体证据）：
- `name` / `degree` / `work_years`（脚本硬门槛过滤依据）
- `work_experience[].company` / `position` / `start` / `end` / `duration` / `responsibility`
- `project_experience[].name` / `role` / `start` / `end` / `duration` / `description` / `achievement`
- `education[]`（school_tier 查表 + 专业匹配）
- `certifications[]`（英语 / 计算机证书是辅助证据）
- `skills`（JD 关键词命中证据；空串也保留）
- 顶层 `geek_id` / `job_id`（从 `_meta` 抽出，供 score_resumes.py 去重）

**额外**：
- 顶层加 `__meta__` 块标 source / source_index / generated_at，方便反查
- 写 `_manifest.json`（文件清单 + 字节数 + geek_id）和 `_skipped.json`（被跳过的 ok=false / 缺 name 的简历）

## 工作区路径约定（新设计 · 2026-07-29+）

**所有数据统一存放在 `~/Desktop/boss-hr-output/<encryptJobId>/` 下**，**目录名直接用 BOSS 的 `encryptJobId`**（不再用中文岗位名）。`job_name` 仅作为 `jobs.json` 里的可读元数据。

```
~/Desktop/boss-hr-output/
├── jobs.json                               # JobRegistry：encryptJobId → {name, company}
└── <encryptJobId>/                         # 目录名 = BOSS 的 encryptJobId
    ├── state/                              # 跨 run 保留（不覆盖）
    │   ├── candidate_pool.json
    │   ├── download_state.json
    │   ├── resumes_master.json             # 累计成功简历（含 _meta）
    │   ├── collection_state.json
    │   ├── scored_state.json
    └── runs/
        └── <run_id>/                       # 一次筛选任务
            ├── <run_id>_screening_report.html
            └── process/
                ├── job_detail.json              ← Step 1: boss_jd.py 输出
                ├── recommend_geek_ids.json      ← Step 2a: list 输出
                ├── new_resumes.json             ← Step 2b: download 输出
                ├── scoring/                     ← Step 3: prepare_scoring_inputs.py 输出
                │   ├── manifest.json             # 候选人清单 + status（pending/scored/missing）
                │   ├── _skipped.json             # 被跳过的简历
                │   ├── inputs/candidate_<geek_id>.json   # LLM 读这里
                │   └── outputs/candidate_<geek_id>.json  # LLM 落盘点（每评一个立即写一份）
                ├── _llm_scores.json             ← Step 3: collect_llm_scores.py 合并产物
                ├── screening_results.json       ← Step 3: score_resumes.py 输出
                ├── failed_resumes.json
                └── greet_log.json               ← Step 5: auto_greet.py 输出
```

> 上游 `boss-job-detail` / `boss-recommend-downloader` 已自动写入此目录，下游脚本（`score_resumes.py` / `generate_html_report.py` / `auto_greet.py`）通过 `--input/--output` 读取此目录。
>
> `JobOutputManager` 提供的标准路径属性：`jd_path` / `recommend_geek_ids_path` / `new_resumes_path` / `screening_results_path` / `report_path` / `run_summary_path`。
>
> **同一 run 必须传同一个 `--run-id`** 给所有脚本（list / download / score / HTML / greet），产物才落在同一个 `runs/<run_id>/`。
>
> **同一 job 必须传同一个 `--encrypt-job-id`** 给所有脚本，工作区目录才一致。

---

## LLM 评分输入 schema

```json
[
  {
    "name": "候选人丙",
    "school": "信阳农林学院/机械设计/本科",
    "work_years": "3 年",
    "match_type": "示例公司 · 汽车零部件三维设计",
    "dims": {
      "exp": 80,
      "skill": 65,
      "proj": 60,
      "major": 100
    },
    "highlights": ["3 年 CATIA", "参与产品设计项目"],
    "concerns": ["做的是轮端非车架"],
    "advice": "强烈建议电话沟通..."
  }
]
```

**字段说明**：

| 字段 | 必填 | 说明 |
|------|:----:|------|
| `name` | 是 | 候选人姓名 |
| `school` | 是 | 校名（脚本自动拆出纯校名） |
| `work_years` | 否 | 工作年限 |
| `match_type` | 否 | 当前岗位 / 业务方向 |
| `dims.exp` | 是 | LLM 评 0-100 最终分（工作经验：综合年限 + 对口度 + 实操深度） |
| `dims.skill` | 是 | LLM 评 0-100 最终分（专业技能） |
| `dims.proj` | 是 | LLM 评 0-100 最终分（项目经历） |
| `dims.major` | 是 | LLM 评 0-100 最终分（专业匹配） |
| `dims.edu` | **否** | 会被 `validate_score` 强制覆盖 |
| `school_name` | **否** | 备选字段，优先级高于 `school` 拆分 |
| `highlights` | 否 | 候选人亮点（推荐动作背景） |
| `concerns` | 否 | 候选人顾虑（不推荐原因 / 待确认问题） |
| `advice` | 否 | 个性化建议（推荐/待定动作方向） |

**注意**：
- 4 个 LLM 评分维度**全部是最终分**（0-100），脚本不会再做任何乘法 / 折扣
- `school` 字段允许任意格式，脚本智能拆出纯校名（支持 `/ · （ (` 等分隔符）
- LLM **不要评** `edu`，会强制被 `school_tier` 覆盖

---

## 5 维度评分方法（理工类通用）

> 适用于一切工程/技术岗（机械、车辆、电子、材料、自动化、化工、土木、软件等）。LLM 评分时结合具体 JD 的核心技能清单与方向，按本表锚点给 0–100。**所有维度给的都直接是最终分**。

| 维度 | 权重 | 评分方 | 评分主体 |
|------|:----:|--------|----------|
| **学历** | **25%** | `school_tier` 查表（校名→档次分）；可选本/硕/博层次加成 | **脚本**（强制） |
| **工作经验** | **25%** | 综合考虑工作年限 + 与 JD 对口度 + 实操深度，给最终分 | **LLM** |
| **专业技能** | **25%** | JD 核心技能覆盖度 × 实操深度 | **LLM** |
| **项目经历** | **15%** | 项目与岗位的相关度 × 复杂度 × 角色 | **LLM** |
| **专业匹配** | **10%** | 专业与 JD 的对口度（优先/相关/弱相关/无关） | **LLM** |

### 维度评分锚点

**① 学历 edu（脚本查表，LLM 不评）**
- 分数取 `school_tier`：C9=100 / 985=92 / 211=85 / 双一流=77 / 一本公办=71 / 二本公办=62 / 民办=53
- 表外学校：edu 显示"缺失"，建议人工复核（可给默认 60 并标"需复核"）
- （可选扩展）层次加成：硕士 +8、博士 +12，封顶 100——由脚本读 `degree` 字段实现

**② 工作经验 exp（LLM 评最终分 0–100）**

LLM 在评 exp 时综合以下 3 个因素，给一个**最终分**：

- **工作年限**（参考锚点）：
  - ≥8 年 = 95 / 5–7 年 = 85 / 3–4 年 = 75 / 1–2 年 = 60 / <1 年 = 45
- **与 JD 对口度**（参考锚点，已并入最终分）：
  - 精准对口（与 JD 核心方向完全一致）= 不折扣
  - 行业相关但非精准（测试/工艺/验证/零部件/相近子领域）= 视情况打 0.7×基础分附近
  - 完全跨行业（纯销售/行政/文科背景）= 视情况打 0.4×基础分附近
- **实操深度**（参考锚点）：
  - 能独立负责核心模块 + 有可验证产出 = 锚点 +5
  - 仅参与执行 / 无量化成果 = 锚点 −5

> 以上三因素**LLM 在打分时一次性综合考虑**，直接给出最终分。脚本不参与任何乘法。

**③ 专业技能 skill（LLM 评最终分 0–100）**
- 按 JD 列出的核心技能清单评估"覆盖度 × 熟练度"：
  - 全覆盖且能独立负责核心模块 = 85–100
  - 核心技能 70%+ 且较熟 = 70–84
  - 覆盖 40-70% 或仅部分了解 = 55-69
  - 覆盖 <40% 或仅字面提及 = 40-54
  - 有 JD 硬性要求但不会的"硬伤"：该档下限再 −10

**④ 项目经历 proj（LLM 评最终分 0–100）**
- 按"与 JD 岗位的相关度 + 复杂度 + 担任角色"：
  - 主导本岗核心项目（0–1 设计/量产落地）= 85–100
  - 重要角色参与核心项目 = 70–84
  - 边缘/支持角色、或项目仅部分相关 = 55–69
  - 非相关但体现工程能力 = 40–54
  - 无可验证项目 / 完全无关 = <40

**⑤ 专业匹配 major（LLM 评最终分 0–100）**
- 以 JD 要求的对口专业为"优先"基准，按专业大类映射（理工类通用）：
  - 优先=100：JD 直接点名的对口专业（随岗而定，如机械设计/车辆工程/材料成型/自动化/电子/化工等）
  - 相关=80：同大类工科（机械类、车辆类、材料类、自动化/机电、土木、化工、计算机偏硬等相近领域）
  - 弱相关=60：基础/交叉学科（力学、数学、物理、计算机偏软、工业工程等）
  - 无关=40：文科、经管、艺术、生化医药等非工程背景
  - 跨专业但有扎实对口课程 + 项目经历的，按"相关"档处理

### 评分公式

```
单维度加权分 = 原始分 (0-100) × 该维度权重
总分 = Σ(所有维度加权分)
```

**示例 A（精准对口，3 年结构设计）**：
```
edu=62, exp=80, skill=65, proj=60, major=100
→ 62×0.25 + 80×0.25 + 65×0.25 + 60×0.15 + 100×0.10
→ 15.5 + 20.0 + 16.25 + 9.0 + 10.0 = 70.75 → "推荐"（≥70）
```

**示例 B（行业相关非精准对口，3 年结构测试）**：

LLM 综合评估后**直接给 exp 最终分 = 56**（已包含"年限 75 × 对口度 0.7 ≈ 53" 的折扣判断）。
```
edu=62, exp=56, skill=65, proj=60, major=100
→ 62×0.25 + 56×0.25 + 65×0.25 + 60×0.15 + 100×0.10
→ 15.5 + 14.0 + 16.25 + 9.0 + 10.0 = 64.75 → "待定"（≥60）
```

### Tier 判定

```python
def calc_tier(total):
    if total >= 70: return "推荐"
    if total >= 60: return "待定"
    return "不推荐"
```

---

## 学校分档表（脚本内置，500+ 学校）

| 档次 | 分数 | 示例学校 |
|------|:----:|----------|
| C9 | **100** | 清华、北大、复旦、交大、浙大、中科大、南大、哈工大、西交 |
| 985 | **92** | 其他 30 所 985 高校 |
| 211 | **85** | 非 985 的 211 高校（如江南大学、苏州大学、华东理工） |
| 双一流 | **77** | 南方科技大学、上海科技大学、中国科学院大学 |
| 一本公办 | **71** | 深圳大学、广东工业大学、西安理工大学、杭州电子科技大学 |
| 二本公办 | **62** | 辽宁工业大学、信阳农林学院、太原工业学院、滁州学院、长江师范学院 |
| 民办/独立学院 | **53** | 燕京理工学院、黄河科技学院、郑州工商学院、四川工业科技学院 |

> 完整 500+ 学校列表见 `scripts/school_tier.py`。
> 不在表内的学校：返回 `score=None`，edu 维度显示"缺失（XX 不在学校表）"。

---

## LLM 评分调用示例

```python
from score_resumes import validate_score

score = {
    "name": "候选人丙",
    "school": "信阳农林学院/机械设计/本科",
    "work_years": "3 年",
    "match_type": "示例公司 · 汽车零部件三维设计",
    "dims": {
        "exp": 80,        # LLM 评最终分
        "skill": 65,      # LLM 评最终分
        "proj": 60,       # LLM 评最终分
        "major": 100      # LLM 评最终分
        # edu 不需要填
    },
    "highlights": ["3 年 CATIA 三维设计", "参与产品设计项目"],
    "concerns": ["做的是轮端非车架本体", "无 CAE 仿真经验", "无焊接/工艺经验"],
    "advice": "专业对口 + 设计经验真实，建议电话沟通是否有车架/底盘结构项目经验"
}
score = validate_score(score)
# → score["dims"]["edu"] = 62（二本公办，school_tier 查表）
# → score["total"] = 69.8
# → score["tier"] = "待定"
# → score["dims_edu_reason"] = "二本公办（school_tier 查询：信阳农林学院）"
```

---

## 输出 schema（screening_results.json）

```json
{
  "job_name": "机械工程师",
  "meta": {
    "title": "机械工程师 · 简历筛选报告",
    "subtitle": "LLM 主导评分 + school_tier 学历分档校准",
    "job": {
      "name": "...",
      "company": "...",
      "location": "...",
      "salary": "...",
      "experience_required": "...",
      "degree_required": "..."
    },
    "type_judgment": {"type": "技术岗", "reason": "..."},
    "core_requirements": ["..."]
  },
  "summary": {"total": 32, "recommend": 0, "pending": 2, "reject": 30},
  "dimension_labels": ["学历", "工作经验", "专业技能", "项目经历", "专业匹配"],
  "candidates": [
    {
      "rank": 1,
      "name": "候选人丙",
      "tier": "待定",
      "total": 69.8,
      "school": "信阳农林学院/机械设计/本科",
      "work_years": "3年",
      "current_role": "汽车零部件三维设计（轮端）",
      "dimensions": [
        {
          "pct": 62,
          "weighted": 15.5,
          "weight": 25,
          "reason": "二本公办（school_tier 查询：信阳农林学院）"
        }
      ],
      "highlights": ["..."],
      "concerns": ["..."]
    }
  ],
  "actions": {
    "recommend": [{"name", "score", "background", "action"}],
    "pending":   [{"name", "score", "strengths", "action"}],
    "reject":    [{"name", "score", "concerns"}]
  }
}
```

---

## 注意事项

- LLM 评 4 维度时务必读完完整简历再打分，避免"看一半就判断"
- 测试 / 设计 / 验证 / 仿真等职能差异要识别（如底盘电控功能测试 ≠ 车架结构设计）
- 学校档次 / tier 阈值 / 公式权重都由脚本控制，LLM 不要尝试覆盖
- exp 维度给的分数就是最终分，**不要再额外标 industry_fit / 对口度系数**，这些已经综合在 exp 分里了
- highlights / concerns / advice 是个性化建议的核心，必须基于候选人实际经历