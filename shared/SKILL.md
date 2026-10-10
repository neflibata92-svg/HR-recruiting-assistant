---
name: shared
description: |
  **基础模块：CDP 连接 + 招聘者岗位目录。** 提供全工具包依赖的底层能力：
    - `cdp_preflight.py`：连 Edge 9222 + 检查 BOSS 招聘者 session（zp_at/wt2/bst cookie）+ 识别当前页面
    - `recruiter_job_catalog.py`：通过浏览器内 fetch 拿 BOSS 后端岗位列表（替代 boss_agent_cli 的 hr jobs list）

  **触发场景**：
  - 任何业务脚本需要连 CDP 浏览器时 → `from cdp_preflight import connect_cdp, check_login`
  - 需要拉招聘者岗位列表 / 解析 encryptJobId 时 → `from recruiter_job_catalog import list_jobs, resolve_recruiter_job, fetch_job_detail`

  **不触发场景**：
  - 仅需要完整 JD 文本 → 用 `boss-job-detail/scripts/boss_jd.py`（导航 BOSS 编辑页抓 iframe）
  - 需要候选人简历 / 推荐牛人 → 用 `boss-recommend-downloader`

  **历史**：2026-07-31 重构，替代第三方 boss_agent_cli 的依赖。
type: lib
---

# shared —— 基础模块

> 本目录是全工具包依赖的 Python 库。**不是入口**，不被任何 AI 智能体当作 Skill 直接加载。
> 业务脚本（`boss_jd.py` / `recommend_list.py` 等）`import` 这些模块即可。

## 模块清单

| 模块 | 角色 | 主要导出 |
|---|---|---|
| `cdp_preflight.py` | CDP 连接 + 登录态探测 | `connect_cdp`, `CDPSession`, `check_login`, `get_cookies`, `RECRUITER_REQUIRED_COOKIES` |
| `recruiter_job_catalog.py` | 招聘者岗位目录 | `list_jobs`, `resolve_recruiter_job`, `fetch_job_detail`, `JOB_LIST_URL`, `JOB_EDIT_URL` |
| `output_manager.py` | 文件路径管理（`JobOutputManager`） | `JobOutputManager`, `resolve_encrypt_job_id`, `OUTPUT_ROOT` |
| `run_orchestrator.py` | run_id 生命周期（`RunOrchestrator`） | `create_new_run`, `bind_existing_run`, `finish` |
| `job_resume_store.py` | 跨 run 累计简历/评分去重 | `JobResumeStore`, `is_scored`, `mark_scored` |
| `job_registry.py` | encryptJobId ↔ jobName 元数据 | `JobRegistry` |
| `cli_runner.py` | Windows PowerShell 安全的 CLI 执行层 | `run_python_cli`（**白名单 9 个 tool**） |
| `confirm_run.py` | 用户确认门（翻 `run.json.confirmed=true`） | CLI 子命令 |
| `fix_encoding.py` | Windows UTF-8 stdout | 自动 import 即生效 |
| `human_interaction.py` | 智能体交互辅助 | — |

---

## `cdp_preflight.py` —— CDP 连接 + 登录态探测

### 设计动机

本工具包**不依赖**任何第三方 CLI（包括早期项目曾用的 `boss_agent_cli`
的 `boss login` / `boss me` / `boss status` 等登录检测命令）。本模块用 patchright
直连 Edge CDP，自己判断：

- Edge 是否在指定端口（如 `http://localhost:9222`）跑着
- BOSS 招聘者 session 是否有效（`zp_at` + `wt2` + `bst` 三 cookie 都在且非空）
- 当前页面是 `recommend` / `chat` / `job_edit` / `login` / `unknown`

所有 BOSS HTTP 调用（`recruiter_job_catalog` 的 `list_jobs` 等）都走**浏览器内 fetch**（`page.evaluate('fetch(...)')`），
复用浏览器真实 TLS 指纹 + 自动带 cookie，**不需要单独同步 `__zp_stoken__`**。

### 接口

```python
from cdp_preflight import (
    connect_cdp,         # 函数
    check_login,         # 函数
    get_cookies,         # 函数
    CDPSession,          # dataclass
    RECRUITER_REQUIRED_COOKIES,  # tuple: ('zp_at', 'wt2', 'bst')
)

# 1) 连 Edge
session = connect_cdp()                    # 默认 http://localhost:9222
session = connect_cdp("http://1.2.3.4:9222", timeout_ms=15000)

# 2) 检查登录
state = check_login(session)
# state = {
#   'logged_in': True/False,
#   'cookies': {
#     'zp_at': True/False,
#     'wt2': True/False,
#     'bst': True/False,
#     'present': [...],   # 所有 cookie 名
#     'total': int,
#   },
#   'current_url': 'https://www.zhipin.com/web/chat/recommend',
#   'page_kind': 'recommend' | 'chat' | 'job_edit' | 'login' | 'unknown',
# }

# 3) 取 cookie（HTTP 库复用）
cookies = get_cookies(session)  # {'zp_at': '...', 'wt2': '...', ...}

# 4) 关闭（不关 Edge，只关 playwright 进程）
session.disconnect()
```

### 异常

| 场景 | 行为 |
|---|---|
| patchright 未安装 | `RuntimeError("patchright 未安装...")` |
| 9222 端口无进程 | `RuntimeError("CDP 不可达: http://localhost:9222 (...)")` |
| 连上但无 context/page | `RuntimeError("CDP 已连，但 browser 没有 context...")` |

### 失败判定（业务侧怎么用）

```python
state = check_login(session)
if not state['logged_in']:
    missing = [k for k, v in state['cookies'].items() if not v and k in RECRUITER_REQUIRED_COOKIES]
    raise RuntimeError(f"BOSS 未登录，缺 cookie: {missing}；请在 9222 Edge 窗口扫码")

if state['page_kind'] == 'login':
    raise RuntimeError("BOSS 已踢回登录页，请重新扫码")

if state['page_kind'] == 'unknown':
    raise RuntimeError("当前页面不是 BOSS 域，请把 Edge 切到 BOSS 后再试")
```

---

## `recruiter_job_catalog.py` —— 招聘者岗位目录

### 设计动机

本工具包**不依赖**任何第三方 CLI（包括早期项目曾用的 `boss_agent_cli` 的
`boss --role recruiter hr jobs list` 命令）。本模块通过 patchright 连 CDP，
在已登录的浏览器 context 里调 `fetch` 打
`https://www.zhipin.com/wapi/zpjob/job/chatted/jobList`（GET），
复用浏览器 TLS 指纹 + 自动带 cookie，**不依赖 stoken/手写 session.enc 同步**。

### BOSS 后端 API（来自 boss_agent_cli/api/recruiter.yaml）

| URL | 方法 | 用途 |
|---|---|---|
| `/wapi/zpjob/job/chatted/jobList` | GET | 招聘者岗位列表 |
| `/wapi/zpjob/job/edit?encJobId=...&lid=&encAtsJobId=` | GET | 单个岗位的 JSON 详情 |

BOSS 响应 schema（已验证）：

```json
{"code": 0, "message": "Success", "zpData": [
  {"encryptJobId": "DemoJob...", "jobId": 111222333, "jobName": "...", "description": "...",
   "salaryDesc": "15-20K", "address": "宁波", "jobOnlineStatus": 1, ...},
  ...
]}
```

`zpData` 直接是 list（不是 `{"list": [...]}` 那种二次包装）。

### 接口

```python
from recruiter_job_catalog import (
    list_jobs,              # 函数：拉所有岗位
    resolve_recruiter_job,  # 函数：按 query 定位单个岗位
    fetch_job_detail,       # 函数：拿单个岗位 JSON 详情（结构化字段）
    JOB_LIST_URL,           # 常量
    JOB_EDIT_URL,           # 常量
    BASE_URL,               # 常量 'https://www.zhipin.com'
)

# 1) 列岗位
result = list_jobs()
# result = {
#   'ok': True/False,
#   'command': 'recruiter-jobs-list',
#   'schema_version': '1.0',
#   'data': [{...}, ...],      # 或 None（失败时）
#   'pagination': None,
#   'error': {'code': str, 'message': str} | None,
#   'hints': None,
# }
if not result['ok']:
    raise RuntimeError(f"list_jobs 失败: {result['error']}")
for job in result['data']:
    print(job['encryptJobId'], job['jobName'], job['salaryDesc'])

# 2) 解析 query
job = resolve_recruiter_job('DemoJobId000000000000000000001')   # eid 精确
job = resolve_recruiter_job('111222333')                        # jobId 精确
job = resolve_recruiter_job('结构设计、研发工程师')         # jobName 精确
job = resolve_recruiter_job('工程师')                          # 模糊（含子串）
job = resolve_recruiter_job('不存在的岗位xxx')                  # → None
# job = {'encryptJobId', 'jobId', 'jobName', 'address', 'salaryDesc', ...}

# 3) JSON 详情
detail = fetch_job_detail('DemoJobId000000000000000000001')
# detail = {'ok': True, 'command': 'recruiter-jobs-detail', 'data': {...BOSS 原始 JSON...}}
```

### query 匹配规则

`resolve_recruiter_job(query)` 按以下顺序找：

1. **encryptJobId 精确**（最权威，找到就立刻返回）
2. **jobId 精确**（`str/int` 兼容）
3. **jobName 精确**
4. **jobName 含 query 子串**（模糊，第一个匹配）

### 失败码（`error.code`）

| code | 含义 |
|---|---|
| `CDP_UNREACHABLE` | 9222 没进程 / patchright 没装 |
| `AUTH_REQUIRED` | zp_at/wt2/bst 缺失（已附每个 cookie 的状态） |
| `FETCH_ERROR` | 浏览器内 fetch 抛异常 |
| `BOSS_HTTP_ERROR` | BOSS 后端返回非 200 |
| `PARSE_ERROR` | BOSS 响应非 JSON 或 schema 不可识别 |

### 注意

- **`fetch_job_detail` 是结构化 JSON 详情**，跟 `boss_jd.py` 抓 iframe DOM（含富文本描述）是两套。
  - 业务侧一般用 `boss_jd.py` 拿完整 JD
  - 本函数用于「快速校验岗位存在」或「辅助对比」
- 真实 Edge TLS 指纹 + 自动 cookie，不需要管 `__zp_stoken__`
- 每次调用 `connect_cdp()` 是有成本的（patchwright 实例化约 1-2s）。
  在一个业务脚本里尽量复用同一个 session。

---

## 输出路径管理（`output_manager.py`）

```python
from output_manager import JobOutputManager

out = JobOutputManager(
    job_name='结构设计、研发工程师',
    encrypt_job_id='DemoJobId000000000000000000001',
    run_id='2026-01-01_000000',   # 必填（新任务由 RunOrchestrator 创建）
)

# 路径属性
out.jd_path              # job_detail.json
out.new_resumes_path     # new_resumes.json
out.recommend_geek_ids_path  # recommend_geek_ids.json
out.screening_results_path   # screening_results.json
out.report_path          # HTML 报告
out.get_process_path('foo.json')  # 通用 process/ 下文件
```

## run_id 生命周期（`run_orchestrator.py`）

```python
from run_orchestrator import RunOrchestrator

orch = RunOrchestrator(
    job_name='结构设计、研发工程师',
    encrypt_job_id='DemoJobId000000000000000000001',
)

# 新任务（boss_jd.py 入口）
run_id = orch.create_new_run()      # 自动生成 YYYY-MM-DD_HHMMSS

# 继续旧任务（其它脚本入口）
run_id = orch.bind_existing_run('2026-01-01_000000')

# 标记步骤
orch.mark_done('jd', run_id=run_id)
orch.init_run_state(run_id)        # 翻 confirmed=false，等用户确认
orch.finish(run_id)                # 整轮跑完（默认 auto_greet 成功时自动调）
```

详细铁律见 `boss-hr-auto/SKILL.md` 的 `## 🚨 run_id 铁律` 章节。

---

## Windows 环境编码

`fix_encoding.py` 在所有 CLI 脚本入口都 `import`，强制 stdout 为 UTF-8。
**仍然推荐**：跑脚本时显式用 `python -X utf8 ...` 或设 `PYTHONIOENCODING=utf-8` 环境变量。

PowerShell / cmd 中文参数解析不稳定：所有 CLI 调用应通过 `cli_runner.py`（参数数组，不拼字符串）。

---

## cli_runner 工具白名单

| tool 名 | 对应脚本 | 用途 |
|---|---|---|
| `boss_jd` | `boss-job-detail/scripts/boss_jd.py` | Step 1：提取 JD |
| `confirm_run` | `shared/confirm_run.py` | 用户确认门 |
| `recommend_list` | `boss-recommend-downloader/scripts/recommend_list.py` | Step 2a：候选人列表 |
| `recommend_download` | `boss-recommend-downloader/scripts/recommend_download.py` | Step 2b：下载简历 |
| `prepare_scoring_inputs` | `resume-screener/scripts/prepare_scoring_inputs.py` | Step 3a：净化层（拆 scoring/inputs/） |
| `collect_llm_scores` | `resume-screener/scripts/collect_llm_scores.py` | Step 3b：合并 LLM 评分 |
| `score_resumes` | `resume-screener/scripts/score_resumes.py` | Step 3c：edu 校准 + 加权 |
| `generate_html_report` | `html-report/scripts/generate_html_report.py` | Step 4：HTML 报告 |
| `auto_greet` | `boss-hr-greet/scripts/auto_greet.py` | Step 5：自动打招呼 |

白名单外 tool 一律拒绝（ValueError）；脚本路径逃逸（`../`）也拒绝。