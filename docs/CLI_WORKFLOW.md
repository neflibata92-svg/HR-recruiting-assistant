# boss-hr CLI 工作流（GitHub 用户 / 开发者文档）

> 面向 GitHub 用户和开发者，**不是** Agent Skill。
> Agent Skill 看 [`boss-hr-auto/SKILL.md`](../boss-hr-auto/SKILL.md)。

---

## 1. 八个公开命令

| 命令 | 作用 | 何时调 |
|---|---|---|
| `boss-hr start` | 创建新 run，停在人工确认门（v1.1.2 自动启动 Edge + 等登录） | 用户说"开始一个筛选任务" |
| `boss-hr confirm` | `confirmed` 翻 true；**不**入 `steps_done`（不依赖浏览器） | 用户回复"继续"后第一件事 |
| `boss-hr fetch --count N` | 拉推荐列表 + 下载 N 份简历（v1.1.2 自动启动 Edge） | confirm 后 |
| `boss-hr score` | 评分协调（一次返回 1 位候选人；不依赖浏览器） | fetch 后循环到 `scoring_complete` |
| `boss-hr report` | 生成 HTML 报告（不依赖浏览器） | `scoring_complete` 后 |
| `boss-hr greet` | 给 ≥70 分候选人打招呼（v1.1.2 自动启动 Edge；需用户明确批准） | 用户明确要求时 |
| `boss-hr doctor` | **诊断工具**（环境检查 + 可选启动专用 Edge）；**不是** start 的必经前置 | 仅在自动启动失败时排查 |
| `boss-hr status` | 读 `runs/<run_id>/run.json` + process 目录（不依赖浏览器） | 任何时候想看当前 run 状态 |

### v1.1.2 浏览器自动恢复

start / fetch / greet **共用** `boss_hr/adapters/browser_environment.ensure_browser_ready`：

1. 检查 9222 端口；未监听 → 自动启动**专用** Edge
   （`--user-data-dir=%LOCALAPPDATA%\boss-hr-edge-profile` + `--remote-debugging-port=9222`，
   **不**污染用户日常 Edge profile）。
2. 连接 CDP，检查 BOSS 登录态（`zp_at` / `wt2` / `bst` cookie）。
3. 已登录 → 继续执行业务。
4. 未登录 → 自动打开 BOSS 招聘者登录页，轮询等待（默认 20 秒）。
5. 超时仍未登录 → 返回 `status=waiting_user_login`（**不是错误**），
   `next_action=retry_same_command`，**不创建 run**。
6. 智能体停下，告诉用户"已在专用 Edge 中打开登录页，请登录后回复“好了”
   重试同一条 start"。

`confirm` / `score` / `report` / `status` 不依赖浏览器，**绝不**触发
Edge 自动启动。

`boss-hr doctor` 仍是独立诊断工具，但**不再是 start 的必经前置**。
仅当自动启动失败（`EDGE_LAUNCH_FAILED` / `CDP_NOT_RUNNING` 超时）、CDP 可连
但 BOSS 始终未登录、Edge 缺失时使用。

调试可选：

- `--no-auto-launch`：缺 CDP 时直接返回 `CDP_NOT_RUNNING`，跳过自动启动。
- `--login-wait-seconds N`：调整等待登录秒数（默认 20）。

## 2. 完整流程图

```
   ┌─────────────────────────────────────────────────────────────┐
   │ 1. boss-hr start <query> --job-name ... --encrypt-job-id ... │
   │    ├─ 9222 未开 → 自动启动专用 Edge（v1.1.2）              │
   │    ├─ 未登录    → 打开 BOSS 登录页 + 轮询 20s              │
   │    │            ├─ 登录成功 → 继续业务                       │
   │    │            └─ 超时     → status=waiting_user_login     │
   │    │                          next_action=retry_same_command│
   │    │                          （不创建 run）                │
   │    └─ 一切就绪 → status: waiting_user_confirmation          │
   │                  → 返回 run_id                              │
   └─────────────────────────────────────────────────────────────┘
                              ↓
                  ━━━━━━━━ 人工确认门 ━━━━━━━━
                  用户在 BOSS 推荐牛人页面调整筛选
                              ↓
                            用户回复 "继续"
                              ↓
   ┌─────────────────────────────────────────────────────────────┐
   │ 2. boss-hr confirm  --run-id <RID>   （不依赖浏览器）       │
   │    boss-hr fetch    --run-id <RID> --count N （自动 Edge）  │
   │    status: candidates_fetched                               │
   └─────────────────────────────────────────────────────────────�
                              ↓
   ┌─────────────────────────────────────────────────────────────┐
   │ 3. boss-hr score    --run-id <RID>  (LLM 循环；不依赖浏览器)│
   │    第一次: status=waiting_llm                                │
   │      → 智能体读 input_file，按 resume-screener/SKILL.md 评 │
   │        4 维度（exp/skill/proj/major），写 output_file         │
   │      → 再调一次完全相同的 score                              │
   │    第二次: status=scoring_complete                          │
   └─────────────────────────────────────────────────────────────┘
                              ↓
   ┌─────────────────────────────────────────────────────────────┐
   │ 4. boss-hr report   --run-id <RID>  （不依赖浏览器）        │
   │    status: report_ready, data.report_file = <path>          │
   └─────────────────────────────────────────────────────────────┘
                              ↓
                              ╲╱
              ┌───────────────────────────────────┐
              │ 5. boss-hr greet  （可选 + 危险） │
              │    仅在用户明确批准时执行          │
              │    v1.1.2 自动启动 Edge           │
              │    ≥70 分候选人 ≥1 时会真实点击    │
              │    0 候选人时安全跳过（no_candidates）│
              └───────────────────────────────────┘
```

### waiting_user_login 重试

当 step 1 返回 `status=waiting_user_login` 时：

- **不创建 run**、不调用 boss_jd、不写业务产物；
- 智能体告知用户"已在专用 Edge 中打开 BOSS 登录页"；
- 用户在专用 Edge 窗口内扫码登录；
- 用户回复"好了" → 智能体**重试同一条 start 命令**（不传任何新参数）；
- 二次 start 会检测到 Cookie 已生效 → 进入正常业务流。

## 3. start 后为何必须停止

`boss-hr start` 的语义是：**只**创建新 run，**只**返回 `run_id`。
然后智能体必须停下，等用户在 BOSS 网页调整筛选条件后回复"继续"。

这是 BEHAVIOR_V1 的强制约束 —— Step 1 完成后**必须**经人工确认门。
原因：BOSS 推荐结果对筛选条件极敏感（关键词、年龄、薪资、经验），自动跳过
会让 agent 用一个错的推荐池做后续下载/评分。

## 4. run_id 是数据边界

- `run_id` 决定本次任务的所有产物路径
- 同一 `encrypt_job_id` 下可以有多个历史 run；下游命令**必须**显式传
  同一个 `run_id`（来自 start 的返回），禁止扫描 `runs/`、禁止读
  `current_run.json`（已废弃）
- start 不接受 `--run-id`（argparse 拦截，rc=2）

## 5. score 为什么需要多次调用

`boss-hr score` 是个**两阶段状态机**：

| 阶段 | status | 智能体动作 |
|---|---|---|
| 协调 | `waiting_llm` | LLM 评**唯一一位**候选人并写 output_file |
| 收尾 | `scoring_complete` | 已完成，可调 `boss-hr report` |

LLM 不能一次写完所有候选人（违反"run_id 是数据边界" + 难以追溯每位评分）。
所以 LLM 必须按"读一位 → 评一位 → 写一位 → 重调 score"的循环工作。
每次 score 只处理一位候选人。

## 6. greet 为什么必须显式批准

`boss-hr greet` 是**真实写操作**：通过 BOSS 浏览器真实点击"打招呼"按钮，
候选人会收到消息。这件事不可逆。

- 默认按 score≥70 推荐 tier 招呼，最多 10 人
- 不得自动调（`report` 不自动 greet）
- 用户没明确说"打招呼"时**禁止**执行
- 不得为测试降低阈值（70 分是 hard-coded）
- 不得给不推荐候选人强制点名发送（`--only-names` 是合法但需用户确认）

## 7. 当前不支持

- `continue` — 旧 run 续跑
- `batch` / `--batch-size` / `--batch` 多批累计合并
- 自动查找最新 run
- 从其他 run 补数据
- 自动跳过人工确认门
- 自动 greet

未来扩展请新建 v1.2+ 版本；不要在当前 CLI 加 `continue` / `batch` 子命令。

## 8. 统一 CLI 与旧脚本的关系

```
通用智能体
  → boss-hr-auto/SKILL.md  （唯一工作流入口）
    → boss-hr CLI           （统一入口）
      → boss_hr/commands/   （7 个薄壳）
        → boss_hr/application/  （业务编排）
          → boss_hr/adapters/legacy_runner.py
            → shared/cli_runner.run_python_cli()
              → 旧业务脚本（boss_jd.py / auto_greet.py / 等）
                → patchright / CDP / BOSS 后端
```

**旧业务脚本保留且活跃**：它们是 `boss-hr` 通过 `cli_runner` 子进程调用的
真实实现。**没有**被复制进 `boss_hr` 包。

## 9. 命令示例（脱敏）

```bash
# 1. 开始任务
boss-hr start "<encryptJobId|jobId|岗位名>" \
  --job-name "<岗位中文名>" \
  --encrypt-job-id "<id>"

# → status=waiting_user_confirmation，run_id=2026-01-01_000000
# → 智能体停下，等用户在 BOSS 推荐牛人页面调整筛选条件

# 用户回复"继续"后：

# 2. 确认 + 拉候选人 + 下载 1 份
boss-hr confirm --job-name "<>" --encrypt-job-id "<>" --run-id "2026-01-01_000000"
boss-hr fetch   --job-name "<>" --encrypt-job-id "<>" --run-id "2026-01-01_000000" --count 1

# 3. 评分循环
boss-hr score --job-name "<>" --encrypt-job-id "<>" --run-id "2026-01-01_000000"
# → status=waiting_llm, candidate_id, input_file, output_file, remaining
# LLM 读 input_file、评 4 维度、写 output_file、再次调：
boss-hr score --job-name "<>" --encrypt-job-id "<>" --run-id "2026-01-01_000000"
# → status=scoring_complete

# 4. 报告
boss-hr report --job-name "<>" --encrypt-job-id "<>" --run-id "2026-01-01_000000"
# → status=report_ready, data.report_file

# 5.（可选 + 用户明确批准时）打招呼
boss-hr greet --job-name "<>" --encrypt-job-id "<>" --run-id "2026-01-01_000000"
```

## 10. 安装与运行

```bash
git clone https://github.com/neflibata92-svg/HR-recruiting-assistant.git
cd HR-recruiting-assistant
python -m pip install -e .

boss-hr --help                # 验证安装
```

**必须**保留完整源码目录；移动源码后重新 `pip install -e .`。
这是 GitHub 源码工具包版本，不是独立 wheel 分发版本。