---
name: boss-job-detail
description: |
  通过 CDP 浏览器提取 BOSS 直聘岗位完整 JD（职责、要求等）。

  **本 Skill 不是工作流入口**。通用智能体应只通过
  [boss-hr-auto](../boss-hr-auto/SKILL.md) → 统一 CLI `boss-hr start` 调用。
  本文档保留作为：业务实现参考 / boss_jd 内部接口 / CDP 行为说明。
---

# BOSS 直聘岗位 JD 提取

> **2026-07-31 重构**：不再依赖第三方 boss_agent_cli。本 skill 内部用
> `shared/recruiter_job_catalog.py`（浏览器内 fetch 拿 BOSS 后端 API）解析
> query → encryptJobId，然后仍走 patchright 直连 CDP 浏览器抓 BOSS 编辑页 iframe
> 拿完整 JD 表单。

## 前提条件

- Edge/Chrome 以 `--remote-debugging-port=9222` 启动
- Boss 招聘者 session 已登录（`zp_at` + `wt2` + `bst` 三 cookie 都存在）
- 可选：用 `shared/cdp_preflight.check_login()` 自检登录态

## 用法

```bash
python scripts/boss_jd.py <查询条件> [--job-name <name>] [--encrypt-job-id <encryptJobId>] [--run-id <id>]
```

参数：
- `<查询条件>` — 三选一：
  - `加密岗位ID`：`DemoJobId000000000000000000002`
  - `数字 jobId`：`123456789`
  - `岗位名称`：`管培生`（精确匹配优先，否则模糊匹配）
- `--job-name`（**必填**，元数据用，目录名不再用它）：岗位中文名，会写入 `jobs.json` 作可读标识。
- `--encrypt-job-id`（**必填**，新设计）：BOSS 返回的 `encryptJobId`，**直接作为工作区目录名**。例如 `DemoJobId000000000000000000001`。5 步脚本（list → download → score → HTML → greet）必须传同一个值，产物才落在同一个工作区目录。
- 也可设环境变量 `BOSS_HR_ENCRYPT_JOB_ID=<encryptJobId>` 作为 fallback（CLI 参数优先）。
- `--run-id`（**可选**，新任务入口）：本次 run 的 ID。
  - **不传** → 自动调 `create_new_run()`，生成新 run_id（`YYYY-MM-DD_HHMMSS`，同秒冲突自动加 `_N` 后缀）。每个新任务必须生成新 run_id——**禁止**沿用旧 run_id。
  - **传 --run-id** → 调 `bind_existing_run(run_id)`，校验 run_dir 存在 + encrypt_job_id 匹配。不通过报错。
  - 拿到 run_id 后**必须**传给 Step 2~5 所有后续脚本（`recommend_list.py` / `recommend_download.py` / `score_resumes.py` / `generate_html_report.py` / `auto_greet.py`）——这些脚本的 `--run-id` 是 `required=True`，不传 argparse 直接退出 2。

> 🚨 **2026-07-30 重构**：不再有 `state/current_run.json`。每个 run 的状态独立写到 `runs/<run_id>/run.json`（含 `confirmed` 标志位、`steps_done`、`finished` 等）。Step 1 完成后 `run.json.confirmed=false`，**必须**等用户在 BOSS 调整完筛选条件后调：
> ```bash
> python -X utf8 shared/confirm_run.py \
>   --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "<run_id>"
> ```
> 把 `confirmed` 切到 true 才能跑 Step 2。

> 🚨 **严格模式**：缺 `--encrypt-job-id`（且未设 `BOSS_HR_ENCRYPT_JOB_ID`）时脚本**直接报错退出**，不会静默回退到中文目录名——避免你以为跑了新路径、实际又落到中文路径的事故。

## 工作流程

1. 用 `shared/recruiter_job_catalog.resolve_recruiter_job(query)` 把 query 解析成 `encryptJobId`
   - 支持三种 query：encryptJobId 精确 / jobId 数字精确 / 岗位名（精确优先，模糊兜底）
   - 返回 `{'encryptJobId', 'jobId', 'jobName', 'address', 'salaryDesc', ...}`
2. 用 patchright 连接 CDP 浏览器
3. 导航到岗位编辑页（`/web/chat/job/edit?encryptId=...`）
4. 等待 iframe 加载完成后提取表单内容（含职位描述富文本 + 关键词 + 福利）
5. 输出到 `~/Desktop/boss-hr-output/<encryptJobId>/runs/<run_id>/process/job_detail.json`

## 输出目录规范（新设计 · 2026-07-29+）

**目录名 = `encryptJobId`**（不再用中文岗位名），`job_name` 仅作为 `jobs.json` 里的可读元数据。

```
~/Desktop/boss-hr-output/
├── jobs.json                               # JobRegistry：encryptJobId → {name, company}
└── <encryptJobId>/                         # 目录名 = BOSS 返回的 encryptJobId（如 DemoJobId000000000000000000001）
    ├── state/                              # 跨 run 保留（不覆盖）
    │   ├── candidate_pool.json
    │   ├── download_state.json
    │   ├── resumes_master.json
    │   ├── collection_state.json
    │   ├── scored_state.json
    └── runs/
        └── <run_id>/                       # 一次筛选任务
            ├── <run_id>_screening_report.html
            └── process/
                ├── job_detail.json              ← 本脚本输出
                ├── recommend_geek_ids.json      ← Step 2a: list 输出
                ├── new_resumes.json             ← Step 2b: download 输出
                ├── scoring/                     ← Step 3a: prepare 输出
                │   ├── manifest.json
                │   ├── inputs/candidate_<geek_id>.json
                │   ├── outputs/candidate_<geek_id>.json
                │   └── _skipped.json
                ├── _llm_scores.json             ← Step 3b: collect 合并产物
                ├── screening_results.json       ← Step 3c: score 收尾产物
                └── greet_log.json               ← Step 5
```

> **路径选择集中在 `shared/output_manager.JobOutputManager`**——CLI 脚本只接收并透传 `--encrypt-job-id`，不参与路径拼接，避免中文路径在 URL/文件 IO 里翻车。
>
> **多机器可移植**：通过环境变量 `BOSS_HR_OUTPUT_DIR` 改工作区根（默认 `~/Desktop/boss-hr-output`）。

## 输出格式

```json
{
  "jobName": "管培生",
  "encryptJobId": "DemoJob...",
  "bodyText": "完整页面文本",
  "formValues": ["岗位职责：...", "职位名称", "..."],
  "parsed": {
    "title": "",
    "positionType": "",
    "location": "",
    "description": "岗位职责 + 任职要求 原文"
  },
  "_meta": {
    "run_id": "2026-07-27_083015",
    "fetched_at": "2026-07-27 08:30:30"
  }
}
```

> **工作区约定**：所有数据统一存放在 `~/Desktop/boss-hr-output/<encryptJobId>/` 下，**目录名直接用 BOSS 的 `encryptJobId`**（避免中文 URL 编码 / 文件名编码问题）。`job_name`（中文岗位名）只作为 `jobs.json` 里的可读元数据。
> 由 `shared/output_manager.JobOutputManager` 统一管理（`boss-recommend-downloader` / `resume-screener` / `html-report` / `boss-hr-greet` 共用同一规范）。
> **6 个 CLI 脚本都必须显式传 `--encrypt-job-id`**（或设 env `BOSS_HR_ENCRYPT_JOB_ID`），缺则直接报错——不会静默回退到中文目录名。

## 技术要点

- BOSS 管理后台为 iframe 架构：主页面是导航壳，表单内容在 `src="/web/frame/job/edit?..."` 的子框架中
- 使用 `domcontentloaded` 而非 `networkidle` 以提速（5-8s）
- **登录态与 HTTP 调用**：所有 BOSS HTTP 调用都走浏览器内 fetch（`page.evaluate('fetch(...)')`），
  复用浏览器真实 TLS 指纹 + 自动带 cookie。**不需要单独同步 `__zp_stoken__`**。
- 岗位 query 解析由 `shared/recruiter_job_catalog.resolve_recruiter_job()` 提供，
  支持精确/模糊匹配、同名兜底；详见 [shared/SKILL.md § recruiter_job_catalog](../shared/SKILL.md)。
- `encryptJobId` 是后续推荐/下载/评分所有步骤的**岗位标识**，会作为 `candidate_key` 的前半段被使用

## 调用示例（boss_jd.py 内部）

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from recruiter_job_catalog import resolve_recruiter_job

# 三种 query 都接受
job = resolve_recruiter_job('DemoJobId000000000000000000001')   # eid 精确
job = resolve_recruiter_job('111222333')                       # jobId 精确
job = resolve_recruiter_job('结构设计、研发工程师')         # jobName 精确
job = resolve_recruiter_job('工程师')                          # 模糊兜底
if not job:
    raise SystemExit(f"岗位未找到")

encrypt_job_id = job['encryptJobId']  # 进入 fetch_jd + 落盘流程
```