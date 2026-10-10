# BEHAVIOR_V1 — v1.1-skill-stable 行为规范

> 本文档锁定 **`v1.1-skill-stable`** 这个 Git 标签对应的工具包行为边界。
> 之后的所有修改必须升级版本号（如 v1.2、v2.0），不再直接修改此冻结版本。

## 1. 已支持

工具包可以**端到端跑完一次新的筛选任务**，流程如下：

```
Step 1   boss_jd.py                   → 写 runs/<run_id>/process/job_detail.json
                                     → 写 runs/<run_id>/run.json (confirmed=false)
   ↓                                  → 智能体停下，等用户回复『继续』
Step 2a  confirm_run.py               → run.json.confirmed = true
Step 2b  recommend_list.py            → 拉候选人 ID 到 recommend_geek_ids.json
Step 2c  recommend_download.py       → 下载 N 份简历到 new_resumes.json
Step 3a  prepare_scoring_inputs.py   → 拆 scoring/{inputs/, outputs/, manifest.json}
                                     → 每份 candidate_<geek_id>.json 是单候选人净化输入
   ↓                                  → LLM 逐份读 inputs/、立即落盘 outputs/ 同一文件名
Step 3b  collect_llm_scores.py       → outputs/ 合并成 _llm_scores.json
                                     → 回写 manifest.status（pending/scored/missing/invalid）
                                     → 幂等可重跑
Step 3c  score_resumes.py            → edu 用 school_tier 校准 + 加权 + tier 判定
                                     → screening_results.json
Step 4   generate_html_report.py      → HTML 可视化报告
Step 5   auto_greet.py                → 给推荐 tier 候选人自动打招呼（CDP 真点击）
```

**说明**：原始验证记录保存在未发布的本地历史克隆中；本仓库不包含真实岗位与候选人数据。

## 2. 不支持

以下场景在 v1.1-skill-stable **未实现或不保证行为正确**，需要升级到后续版本：

| 场景 | 当前行为 |
|---|---|
| **`continue` 续跑** | 没有 `continue` 子命令。run 失败后必须新建 run 重来；旧 run 保留作为审计日志 |
| **`--batch N` 多批累计** | `--batch-size` 和 `--batch` 参数仍存在（CLI 兼容），但**不保证**多批自动合并到同一 `new_resumes.json`。建议单次跑就够 |
| **断点续评循环** | `collect_llm_scores.py` 支持幂等合并（manifest.status 字段），但**没有**自动扫描 missing → 重跑命令的循环 |
| **失败回滚** | Step 2b/c 下载失败时 `failed_resumes.json` 记录，但**不会自动重试**；用户/智能体需手工判断 |
| **并发 run** | 同一 encryptJobId 同时多个 run 会冲突（state/scored_state 共享）；不支持 |
| **跨平台** | 当前在 Windows + Git Bash 验证；macOS / Linux 需自测 |

## 3. 已知的次要问题（不阻断 v1.1）

- `_llm_scores.json` 中 `geek_id` / `job_id` 字段由 `collect_llm_scores.py` 兜底补全，LLM 漏写也不会失败
- `prepare_scoring_inputs.py` 输出 `manifest.json` 包含所有候选人（含 `ok=false` 跳过）；`_skipped.json` 单独记录被跳过的
- `auto_greet.py` 的 `not_found=1` 退出码 0 时 `finish()` 不自动调用，下次跑 `boss_jd.py` 会再创建一个新 run（这是预期行为）

## 4. 完成标准（v1.1-skill-stable 冻结条件）

| 检查项 | 状态 |
|---|---|
| 不依赖任何第三方 BOSS CLI（`boss-agent-cli/` 已删；`requirements.txt` 只剩 `patchright`） | ✅ |
| 业务脚本无 `subprocess boss` 调用 | ✅ |
| `boss_jd.py` 不再 import subprocess；用 `shared/recruiter_job_catalog.resolve_recruiter_job` | ✅ |
| 业务脚本入口都用 `shared/cdp_preflight.check_login` 自检登录态 | ✅ |
| 文档里无 `boss login` / `boss me` / `boss status` 等过时命令示例 | ✅ |
| 文档里无「直接写 `_llm_scores.json`」「不要落分片」等老 LLM 流程描述 | ✅ |
| 文档里无 `batch_1_ids.json` 等过时文件名 | ✅ |
| `run.json` 路径统一写为 `runs/<run_id>/run.json` | ✅ |
| `cli_runner` 白名单 9 个 tool 全通过 `--help` 烟测 | ✅ |
| 端到端冒烟（Step 1→2→3→4）全跑通 | ✅ |
| 17/17 cli_runner 测试 + 6/6 job_registry 测试通过 | ✅ |

## 5. 严格禁止（修改代码时也要遵守）

| 行为 | 原因 |
|---|---|
| ❌ 新增 `spec_*.json` 模板到项目根 | spec 是 cli_runner 的内部调用方式，调用时现构造即可，不应该常驻项目目录 |
| ❌ 改 `requirements.txt` 加第三方依赖 | v1.1 唯一依赖是 patchright；引入第三方需要升到 v2 |
| ❌ 在 `boss_jd.py` / `recommend_*` 加 subprocess 调用 | 必须走 `shared/cdp_preflight` + `shared/recruiter_job_catalog` |
| ❌ 改 `cli_runner.py` 白名单加新 tool | 9 个 tool 已覆盖全流程；加新 tool 必须升级 v1.2 |
| ❌ 改 run_id 数据边界（允许跨 run 找文件） | run_id 是数据边界铁律，破坏它会让审计日志失效 |

## 6. 版本演进路径

| 版本 | 预期方向 |
|---|---|
| `v1-skill-stable` | 历史冻结版（已被 v1.1 取代） |
| `v1.1-skill-stable` | **当前冻结版**：清理文档矛盾；删除 spec 模板；明确实行为边界 |
| `v1.2-skill-stable` | 自动 missing → 重跑评分循环；`continue` 子命令 |
| `v2.0-skill-stable` | 彻底移除所有 BOSS 兼容代码（`boss.exe` 提及、schema 兼容 `data=[]` 等），只保留新模块路径 |

---

> **本版本的所有修改请开新分支**：基于 `v1.1-skill-stable` 拉分支，PR 合入 main 后打新标签。
> 不要直接在 main 上改完再回头打 `v1.1-skill-stable` 覆盖。