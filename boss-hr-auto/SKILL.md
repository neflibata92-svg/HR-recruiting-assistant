---
name: boss-hr-auto
description: |
  BOSS 直聘 HR 简历筛选全流程编排。当用户要求"筛选简历"、"跑 5 步流程"、
  "从岗位到报告"时使用。

  **触发场景**：
  - "筛选简历" / "筛一下这个岗位" / "帮我筛选候选人"
  - BOSS 直聘 HR 工具包全流程一次跑完

  **不触发场景**：
  - 仅问单条消息怎么回复（直接用 message 工具）
  - 非 BOSS 直聘的其他招聘平台

  **行为边界**：详见 [docs/BEHAVIOR_V1.md](../docs/BEHAVIOR_V1.md)。
  v1.1+ 只支持「一次完整的新筛选任务」；continue / batch / 多批累计均不支持。

  **编排入口**：统一 CLI `boss-hr`。**禁止直接调用旧业务脚本**。
type: workflow
---

# BOSS HR 统一筛选流程（v1.1+）

> 入口：`boss-hr` 统一 CLI。下文按步骤顺序调用 8 个公开命令。
>
> **本 Skill 是纯文档**。智能体按步骤顺序逐个调用统一命令。

## 行为边界

**支持**：

- 一次完整的新筛选任务；
- start → confirm → fetch → score → report；
- 用户明确要求时执行 greet。

**不支持**：

- continue / batch / 多批累计；
- 自动查找最新 run；
- 从其他 run 补数据；
- 自动跳过人工确认门。

## 公开命令（v1.1.1 起 8 个：含 doctor）

| 命令 | 作用 |
|---|---|
| `boss-hr doctor` | **环境健康检查 + 启动辅助**（首次或环境未知时先调） |
| `boss-hr start` | 创建新 run，停在人工确认门 |
| `boss-hr confirm` | 把 `confirmed` 翻 true |
| `boss-hr fetch --count N` | 拉候选人列表 + 下载 N 份简历 |
| `boss-hr score` | 评分协调（一次返回 1 位候选人） |
| `boss-hr report` | 生成 HTML 报告 |
| `boss-hr greet` | 给 ≥70 分候选人自动打招呼（需用户明确批准） |
| `boss-hr status` | 读 `runs/<run_id>/run.json` + process 目录 |

**禁止调用旧脚本**：`boss_jd.py` / `confirm_run.py` / `recommend_list.py` /
`recommend_download.py` / `prepare_scoring_inputs.py` / `collect_llm_scores.py` /
`score_resumes.py` / `generate_html_report.py` / `auto_greet.py` /
`cli_runner.py` / spec JSON。

## 浏览器与登录态（v1.1.3 不阻塞扫码等待）

**正常流程直接 `start`**。start / fetch / greet 都自动保证 Edge + BOSS
登录态可用，不需要先跑 `doctor`：

1. start 检查 9222 端口；未监听 → 自动启动**专用** Edge
   （`--user-data-dir=%LOCALAPPDATA%\boss-hr-edge-profile` + `--remote-debugging-port=9222`，
   **不**污染用户日常 Edge profile）。
2. 自动启动后连接 CDP，只等待 CDP 端口/连接就绪（秒级，**不**阻塞扫码等待）。
3. 已登录 → 继续执行 start 业务（实时解析岗位 → 创建 run）。
4. 未登录 → 自动打开 BOSS 招聘者登录页 + 立即返回
   `status=waiting_user_login`（**不是错误**，`ok=true`）。
5. **start 不在 CLI 内阻塞轮询扫码**——避免 Agent / 用户被卡 20s。
   用户在专用 Edge 窗口扫码登录后，**重新执行完全相同的 `boss-hr start` 命令**
   （不传任何新参数），让 CLI 复核登录态。
6. start 收到 `waiting_user_login` 时**不创建 run、不抓 JD、不写 confirmed**。

`doctor` 仍是独立诊断工具，但**不再是 start 的必经前置**。仅当：

- 自动启动 Edge 失败（`EDGE_LAUNCH_FAILED` / `CDP_NOT_RUNNING` 超时）；
- CDP 可连但 BOSS 始终判定未登录；
- Edge 缺失或版本不匹配；

这些**才**用 `doctor` 排查。普通首次使用**不需要**先 doctor。

调试时可加 `--no-auto-launch`：缺 CDP 时直接返回 `CDP_NOT_RUNNING`，
跳过自动启动 Edge。`--login-wait-seconds N`（N>=1）启用旧 v1.1.2 阻塞轮询
路径；**Agent 不应传**该参数，仅作为人工调试兼容选项；
N<=0（含默认值 0）→ start 立即返回 `waiting_user_login`，不阻塞。

## 岗位解析规则（v1.1.1 强制）

智能体**只**需提供：

- 岗位名称（如 `"结构设计、研发工程师"`）
- 或 jobId 数字（如 `111222333`）
- 或完整 encryptJobId（如 `DemoJobId000000000000000000001`）

`start` 内部通过 `shared.recruiter_job_catalog.resolve_recruiter_job(query)`
**实时**调 BOSS 后端岗位目录解析。

**禁止**：

- 读取 `jobs.json` 拿 encryptJobId
- 从历史 run / `job_detail.json` 找 ID
- 读取 `state/` 文件
- 读取历史 HTML 报告
- 扫描最近 run
- 读取 `current_run.json`（已废弃）

### 0. 浏览器（v1.1.3）：start 不阻塞扫码等待

正常流程**直接** `boss-hr start`，不需先 doctor：

- 9222 已开且已登录 → 立即进入 step 1 业务
- 9222 未开 → 自动启动专用 Edge（`%LOCALAPPDATA%\boss-hr-edge-profile`，
  `--remote-debugging-port=9222`，**不**碰日常 Edge profile）
- 自动启动后未登录 → 打开 BOSS 登录页，**立即**返回 `status=waiting_user_login`
  （**不是错误**），`next_action=scan_login_then_repeat_start`，**不创建 run**；
  智能体停下，告诉用户在专用 Edge 中扫码登录，用户明确回复"已登录"后
  智能体**重新执行同一条 start**（不传任何新参数），让 CLI 复核登录态。

调试可选：`--no-auto-launch` 关闭自动启动；`--login-wait-seconds N`（N>=1）
启用旧 v1.1.2 阻塞轮询（**仅人工调试兼容**，Agent 不传；传 0 与不传等价）。

`boss-hr doctor` 仍是独立诊断工具，仅在自动启动失败时使用。

## 标准流程

### 1. 开始任务：`boss-hr start`

```bash
boss-hr start "<岗位名称 | jobId | encryptJobId>"
# 可选: --job-name "<BOSS 真名>" --encrypt-job-id "<一致性校验>"
```

**start 不接受 `--run-id`**（argparse 拦截，rc=2）。每次 start 必须创建新 run。

start 内部通过 `shared.recruiter_job_catalog.resolve_recruiter_job(query)`
**实时**调 BOSS 后端岗位目录解析（不读 `jobs.json`）。

**期望返回**：

```json
{"ok": true, "command": "start", "status": "waiting_user_confirmation",
 "run_id": "<新 run_id>", "encrypt_job_id": "...", "job_name": "...",
 "data": {"job_detail_file": "<path>", "confirmed": false,
          "resolved_from": "live_boss_catalog"},
 "next_action": "confirm"}
```

**特殊错误**：

- `JOB_NOT_FOUND`：BOSS 实时目录找不到 query（智能体不应去读 jobs.json）
- `JOB_AMBIGUOUS`：返回 `data.candidates` 让用户精确指定 encryptJobId
- `JOB_ID_MISMATCH`：用户传的 `--encrypt-job-id` 与实时解析不一致

**拿到 run_id 后立即停下**。向用户说明：

> 请在 BOSS 推荐牛人页面调整筛选条件（关键词、年龄、薪资、经验等），调整完成后回复"继续"。

**禁止**：

- ❌ 同一轮继续执行 `confirm` 或 `fetch`
- ❌ 把 start 输出的 run_id 之外的值传给后续命令

### 2. 用户回复继续：`boss-hr confirm` + `boss-hr fetch`

```bash
boss-hr confirm --job-name "<>" --encrypt-job-id "<>" --run-id "<step1 输出的 run_id>"
boss-hr fetch   --job-name "<>" --encrypt-job-id "<>" --run-id "<>" --count N
```

- `confirm` 翻 `confirmed=true`、写 `user_confirmed_at`；**不入** `steps_done`。
- `fetch --count N` 先 list 再 download；返回 `candidates_fetched`。
- `fetch` 内部**不**触发 score / report / greet。

**run_id 必须来自 step 1**，禁止扫描 `runs/` 找最新、禁止读 `current_run.json`。

### 3. 评分：`boss-hr score` 循环

LLM 循环：

1. 调 `boss-hr score ...`。
2. 若返回 `status=waiting_llm`：**只读**返回的 `data.input_file`；
   按 [resume-screener/SKILL.md §5](../resume-screener/SKILL.md) 评 4 维度
   `exp / skill / proj / major`（0-100 最终分，**不评 edu**）；
   把单个评分 object 写入返回的 `data.output_file`；
   **再调一次完全相同的** `boss-hr score ...`。
3. 若返回 `status=scoring_complete`：进 step 4。

**单候选人约束**：每次 `score` 只处理一位候选人。LLM 不循环写多位。

**评分不改**：`total` 由 5 维度 weighted（edu 25% / exp 25% / skill 25% /
proj 15% / major 10%）算；tier ≥70 推荐 / 60-69 待定 / <60 不推荐。
edu 由 `score_resumes` 用 `school_tier` 强制覆盖，不接受 LLM 赋值。

### 4. 报告：`boss-hr report`

```bash
boss-hr report --job-name "<>" --encrypt-job-id "<>" --run-id "<>"
```

期望返回：

```json
{"ok": true, "command": "report", "status": "report_ready",
 "data": {"report_file": "<绝对路径>"}, "next_action": "greet_optional"}
```

把 `report_file` 路径告诉用户。**report 不自动调 greet**。

### 5. 打招呼：`boss-hr greet`（需用户明确批准）

**只有用户明确要求"打招呼"或"招呼这几个人"时**才执行：

```bash
boss-hr greet --job-name "<>" --encrypt-job-id "<>" --run-id "<>" \
  [--only-names "张三,李四"] [--threshold 70] [--max 10] [--dry-run]
```

**安全约束**：

- 不得降低阈值、不得改分数、不得强制点名不推荐候选人发送；
- score `< 70` 的候选人**不会**被打招呼（`no_candidates=true` 路径）；
- 单 run `finished=true` 仅在 `greeted >= 1` 且 `maybe_finish` 成功时被设置
  （`run.json.finished` ≠ `next_action="done"`）。

### 6. 状态查询：`boss-hr status`

```bash
boss-hr status --job-name "<>" --encrypt-job-id "<>" --run-id "<>"
```

只对**用户明确提供**的 `encrypt_job_id` + `run_id` 执行。**禁止扫描**最新 run。

## 铁律

| # | 规则 |
|---|---|
| 1 | 新任务必须调 `start`；start 不接受旧 run_id |
| 2 | start 后必须停下，等用户回复"继续" |
| 3 | 所有下游命令必须显式使用同一个 `run_id` |
| 4 | 禁止扫描 `runs/` 猜 run_id |
| 5 | 禁止读 `current_run.json`（已废弃） |
| 6 | 禁止借用其他 run 的产物 |
| 7 | 禁止创建 `spec_*.json` 模板 |
| 8 | 禁止直接调旧业务脚本（boss_jd / confirm_run / recommend_* / score_* / generate_html_report / auto_greet） |
| 9 | 禁止调 `cli_runner` 或 `shared.cli_runner.run_python_cli` |
| 10 | 禁止自动 greet（必须用户明确批准） |
| 11 | 禁止 continue / batch / 多批累计 |
| 12 | 禁止为测试而降低阈值、篡改评分 |

## 状态处理

每个命令返回的 `status` 字段决定下一步动作：

| 返回 status | 含义 | 智能体动作 |
|---|---|---|
| `waiting_user_confirmation` | start 完成，等用户回复"继续" | **停下**，告知用户去 BOSS 推荐牛人页面调整筛选条件 |
| `waiting_user_login` | start 自动启动 Edge 后用户未登录 | **停下**，明确告诉用户"CDP 浏览器已经打开，请在浏览器内扫码登录"，**禁止 Agent 盲目循环 start**；用户明确回复"已登录"后，**重新执行完全相同的 `boss-hr start` 命令**（不传任何新参数），让 CLI 复核登录态 |
| `confirmed` | confirm 完成 | 进入 fetch |
| `candidates_fetched` | fetch 完成 | 进入 score 循环 |
| `waiting_llm` | score 需要 LLM 评一位 | 读 input_file、评、写 output_file、**再次调** `boss-hr score` |
| `scoring_complete` | 评分收尾完成 | 进入 report |
| `report_ready` | HTML 报告已生成 | 把 `report_file` 告诉用户；**不**自动 greet |
| `greet_complete` | 本次 greet 命令结束 | 任务结束 |
| （任意 `ok=false`） | 错误 | 见下方错误处理 |

**重要**：`next_action="done"` 只表示"当前 CLI 工作流无下一项自动动作"，
**不等于** `run.json.finished=true`。只有 `maybe_finish()` 在 `greeted>=1`
且 `orch.finish(run_id=...)` 成功时被设置 `run.json.finished=true`。

## 错误处理

统一 CLI 返回非零退出码时：

1. **先**读取 `error.code`：
   - `EDGE_NOT_FOUND` / `CDP_NOT_RUNNING` / `CDP_CONNECT_FAILED` →
     让用户按 `remediation` 启动 Edge / 重连
   - `BOSS_LOGIN_REQUIRED` → 让用户在专用 Edge 中扫码登录
   - `BOSS_PAGE_REQUIRED` → 让用户打开 BOSS 招聘者页面
   - `JOB_NOT_FOUND` / `JOB_AMBIGUOUS` / `JOB_ID_MISMATCH` → 按
     `data.candidates` 或 `remediation.instructions` 重新提供 query
2. 检查 `error.recoverable`：若 `true` 才有可执行恢复路径
3. 按 `error.next_action` / `error.remediation` 引导用户

**禁止**：

- 读 `boss_hr` 源码
- 直接调用旧业务脚本（`boss_jd.py` / `auto_greet.py` 等）
- 用历史 JSON（`jobs.json` / `run.json` / `job_detail.json`）绕过错误
- 把 run 状态（`confirmed` / `finished`）手工改写

常见退出码：`1`（业务层）/ `2`（argparse 缺必填）/
`20`（未 confirm 跑 fetch）/ `23`（run 不存在）/ `24`（run 与岗位不匹配）/
`26`（缺输入文件）/ `27`（缺输出文件）。