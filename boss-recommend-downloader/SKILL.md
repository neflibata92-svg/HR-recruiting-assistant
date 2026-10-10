---
name: boss-recommend-downloader
description: |
  从 BOSS 推荐牛人页面拉候选人列表 + 下载完整在线简历。

  **本 Skill 不是工作流入口**。通用智能体应只通过
  [boss-hr-auto](../boss-hr-auto/SKILL.md) → 统一 CLI `boss-hr fetch` 调用。
  本文档保留作为：业务实现参考 / 旧脚本内部接口 / CDP 行为说明。

  **触发场景**（**内部实现参考**，不要直接调用）：
  - boss-hr fetch 内部经 cli_runner 调 recommend_list + recommend_download

  **不触发场景**：
  - 从沟通/互动页面下载简历（用 boss-resume-downloader，本项目未提供）
  - 仅查看推荐列表（不下载简历）

  **行为边界**：v1.1-skill-stable 只支持**一次拉取**（不超过 50 人）；不保证 batch 累计行为（详见 [docs/BEHAVIOR_V1.md](../docs/BEHAVIOR_V1.md)）。
type: tool
---

# 推荐牛人简历下载

> **核心目标**：安全地从推荐牛人页面拉候选人列表 + 下载完整简历。
>
> **安全级别**：🟢 极低风险（真实 Edge TLS 指纹 + 随机延迟）

---

## 流程

```
Step 2a: scripts/recommend_list.py
  patchright 滚动 + 拦截 geek/list API
        ↓
Step 2b: scripts/recommend_download.py
  patchright + 浏览器 fetch（真实 Edge 指纹）
        ↓
输出: runs/<run_id>/process/new_resumes.json
```

**核心原理**：通过 patchright 在真实 Edge 浏览器内执行 `fetch()` 调用 BOSS API，
使用浏览器真实的 TLS 指纹和 Cookie，与真人操作完全一致。

---

## 前置条件

| 项 | 要求 |
|---|---|
| Python | 3.10+ |
| patchright | `pip install patchright` |
| Edge | `--remote-debugging-port=9222` 启动 |
| BOSS 招聘者 | 扫码登录完成（zp_at/wt2/bst cookie 齐全） |
| Step 1 | 已跑通 `boss_jd.py`，拿到 `encryptJobId` + `run_id` |
| 确认门 | `runs/<run_id>/run.json.confirmed=true` |

登录态由 `shared/cdp_preflight.check_login()` 自检。

---

## Step 2a: 拉候选人列表

**脚本**：`scripts/recommend_list.py`

**原理**：在推荐牛人页面滚动时，前端懒加载调用 `geek/list` API。用 patchright 拦截响应，提取候选人 ID。

### 调用

```bash
python scripts/recommend_list.py \
  --job-name "<岗位中文名>" \
  --encrypt-job-id "<BOSS encryptJobId>" \
  --run-id "<run_id>" \
  --batch-size 25
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | 岗位中文名（jobs.json metadata） |
| `--encrypt-job-id` | 是 | 工作区目录名 = encryptJobId |
| `--run-id` | 是 | 当前 run_id（数据边界） |
| `--batch-size` | 否 | 默认 25；调到 50 也行，但别超过 |

### 输出

`runs/<run_id>/process/recommend_geek_ids.json`

---

## Step 2b: 下载简历

**脚本**：`scripts/recommend_download.py`

**原理**：patchright 在浏览器内 `fetch` `/wapi/zpjob/view/geek/info`，使用真实 Edge TLS 指纹 + Cookie。

### 调用

```bash
python scripts/recommend_download.py \
  --job-name "<岗位中文名>" \
  --encrypt-job-id "<BOSS encryptJobId>" \
  --run-id "<run_id>" \
  --max 5
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | |
| `--encrypt-job-id` | 是 | |
| `--run-id` | 是 | |
| `--max` | 否 | 最多下载多少份（建议 5~10 起步） |

### 输出

| 文件 | 内容 |
|---|---|
| `runs/<run_id>/process/new_resumes.json` | 本次新增成功简历 |
| `runs/<run_id>/process/failed_resumes.json` | 失败列表 |

跨 run 累计简历在 `state/resumes_master.json`（自动去重）。

---

## 完整简历数据结构

```json
{
  "name": "张三",
  "age": "25岁",
  "degree": "本科",
  "work_years": "3年",
  "work_experience": [
    {
      "company": "XX 公司",
      "position": "测试工程师",
      "start": "2023.09",
      "end": "2026.06",
      "duration": "2年9个月",
      "responsibility": "..."
    }
  ],
  "project_experience": [
    {
      "name": "XX 项目",
      "role": "测试工程师",
      "start": "2025.04",
      "end": "2026.06",
      "description": "..."
    }
  ],
  "education": [
    {
      "school": "XX 大学",
      "major": "车辆工程",
      "degree": "本科"
    }
  ],
  "certifications": ["英语四级"],
  "_meta": {
    "encrypt_geek_id": "...",
    "encrypt_job_id": "...",
    "downloaded_at": "..."
  }
}
```

注：`age` / `certifications` / `_meta` 等字段在 Step 3a 净化层会被剥离（详见 [resume-screener/SKILL.md § 净化层字段规则](../resume-screener/SKILL.md)）。

---

## 安全策略

### 真实浏览器指纹

- TLS 指纹 = 真实 Edge 浏览器
- Cookie = 用户真实登录 session
- 请求头 = 浏览器自动添加的标准头
- BOSS 服务器无法与真人操作区分

### 随机延迟（脚本内置）

| 操作 | 延迟 |
|---|---|
| 页面滚动 | 3-6 秒 |
| 获取简历 | 60-120 秒（每 5 份触发一次长延迟） |

### 运行建议

- 推荐工作时间（9:00-18:00）
- 单次建议不超过 50 人
- 遇到"今日查看已达上限"立即停止

---

## 故障排查

### `今日查看已达上限`

BOSS 每日查看简历数量限制。等第二天额度刷新后继续。

### `fetch` 返回空数据或报错

通常是登录 session 过期。在 9222 Edge 窗口里重新扫码登录，然后跑 `shared/cdp_preflight.check_login()` 自检。

### 滚动时没有加载更多候选人

脚本已在 iframe 内滚动。如仍有问题，确认推荐牛人页面已正确加载，且 BOSS 推荐了候选人。