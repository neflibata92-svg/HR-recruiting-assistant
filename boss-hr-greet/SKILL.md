---
name: boss-hr-greet
description: |
  BOSS 直聘 HR 工具包 · 「自动打招呼」。给已打分的高分候选人（或精准点名的候选人）自动点击 BOSS 打招呼按钮，模拟真人操作。

  **本 Skill 不是工作流入口**。通用智能体应只通过
  [boss-hr-auto](../boss-hr-auto/SKILL.md) → 统一 CLI `boss-hr greet` 调用。
  本文档保留作为：业务实现参考 / auto_greet 内部接口 / CDP 行为说明。

  **触发场景**（**内部实现参考**，不要直接调用）：
  - boss-hr greet 内部经 cli_runner 调 auto_greet

  **核心设计**：基于 `state/geek_positions.json` 位置表 + 按 doc_y **倒序招呼**，配合 `frame.evaluate('button.click()')` 直接调 DOM click（不走 page.mouse.click 算坐标），从根上避免"点错位置打开简历详情"。
type: workflow
---
# BOSS 直聘 HR · 自动打招呼

> 本 Skill 是 boss-hr-auto 主流程的 **Step 5**，在评分报告生成后由智能体调用（默认真点击 BOSS，不 dry-run、不二次确认）。
>
> 也支持单独运行（精准点名 / 回头招呼老名单 / 仅刷新位置表）。
>
> 实现脚本：`scripts/auto_greet.py`（本目录内）。

---

## 安装 / 工作区假设

本 Skill 默认按以下约定运行（**不硬编码任何用户的本地路径**）：

| 环境项 | 默认值 | 怎么改 |
|--------|--------|--------|
| 工作区根 | `~/Desktop/boss-hr-output/<encryptJobId>/` | 设环境变量 `BOSS_HR_OUTPUT_DIR=<你想要的路径>`，**整个 toolkit 都会用新路径**（`shared/output_manager.py` 已支持） |
| 岗位目录名 | **BOSS 的 `encryptJobId`**（不再用中文岗位名） | 通过 `--encrypt-job-id` 显式传，或设 env `BOSS_HR_ENCRYPT_JOB_ID` |
| shared 路径 | 自动按 `scripts/` 的相对路径定位（`../../shared`） | 无需配，跟仓库走 |
| 浏览器 CDP | `http://localhost:9222` | 暂无 env 覆盖；如需改请改 `auto_greet.py` 顶部 `CDP_URL` 常量 |

> 其他机器 / WSL / Linux 部署：先 `export BOSS_HR_OUTPUT_DIR=/your/path`，然后按下面的命令直接跑即可。

---

## 主流程调用（推荐）

智能体跑完 Step 4（HTML 报告）后调本步，**必须传与前面各 Step 相同的 `--run-id` 和 `--encrypt-job-id`**。

- **默认行为**：CDP 真实点击 BOSS 打招呼按钮（按 score≥70 推荐 tier 招呼，最多 10 人）
- **跳过**：不调用本 Skill 即可

---

## 单独招呼（不走主流程）

> 🚨 **新接口必传 `--encrypt-job-id`**：与 Step 1/2/3 保持一致。也可以设 env `BOSS_HR_ENCRYPT_JOB_ID` 作为 fallback。缺则直接 `ValueError` 退出（严格模式）。

```bash
# 公共参数
export ENCRYPT_ID="DemoJobId000000000000000000001"
export JOB_NAME="结构设计、研发工程师"

# === 模式 1：默认（一键：自动扫位置 + 倒序招呼）===
python -X utf8 "<项目根>/boss-hr-greet/scripts/auto_greet.py" \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id "$RUN_ID" \
  --only-names "候选人甲,候选人乙"

# === 模式 2：默认按分招呼（≥70 推荐 tier 自动招呼，最多 10 人）===
python -X utf8 "<项目根>/boss-hr-greet/scripts/auto_greet.py" \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id "$RUN_ID"

# === 模式 3：只扫描（不下发，用于调试 / 刷新位置表）===
python -X utf8 "<项目根>/boss-hr-greet/scripts/auto_greet.py" \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id "$RUN_ID" \
  --only-names "候选人甲" --scan-only

# === 模式 4：用已有位置表直接招呼（list 状态未变时省 2 秒扫描）===
python -X utf8 "<项目根>/boss-hr-greet/scripts/auto_greet.py" \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id "$RUN_ID" \
  --only-names "候选人甲" --skip-scan
```

> 默认行为（**不传 --scan-only / --skip-scan**）= 内部自动扫描 + 招呼，**无需分两步跑**。

> Windows PowerShell 中 `<项目根>` 是你克隆 `boss-hr-agent-toolkit` 的目录绝对路径，例如 `C:\code\boss-hr-agent-toolkit`。**不要硬编码到 SKILL 里**——本工具包设计为多机器可移植。

---

## 何时用哪个模式

| 场景 | 用什么 | 备注 |
|------|--------|------|
| "给候选人甲打招呼" | `--only-names "候选人甲"` | 默认自动扫 + 招，最稳 |
| "把所有 ≥70 分的都招呼一遍" | 不传 `--only-names`（按 score 阈值） | threshold 默认 70，max 默认 10 |
| 调试 list / 看招呼位置对不对 | 加 `--dry-run` | 只定位不 click |
| list 状态刚扫过、未变化 | 加 `--skip-scan` | 跳过扫描省 2 秒 |
| 只想刷新位置表，不招呼 | 加 `--scan-only` | 写 `state/geek_positions.json` 后退出 |

---

## CLI 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--job-name` | 结构设计、研发工程师 | 岗位中文名（仅作 `jobs.json` 元数据） |
| `--encrypt-job-id` | **必填** | BOSS 的 `encryptJobId`（= 工作区目录名）；env `BOSS_HR_ENCRYPT_JOB_ID` 可作 fallback |
| `--threshold` | 70 | score 阈值（≥ 阈值的候选人会被打招呼）；`--only-names` 模式下忽略 |
| `--max` | 10 | 最多打招呼人数；`--only-names` 模式下自动 = 名单长度 |
| `--only-names` | - | 逗号分隔，精准点名（与 threshold 同时生效时 --only-names 优先） |
| `--run-id` | （必填） | 本次 run ID（从 Step 1 boss_jd.py 输出取） |
| `--dry-run` | - | 干跑：只定位不 click |
| `--scan-only` | - | 只扫描记位置，不打招呼 |
| `--skip-scan` | - | 跳过扫描，直接用已有位置表打招呼 |

> `--scan-only` 与 `--skip-scan` 互斥（脚本会校验报错）。
> **严格模式**：缺 `--encrypt-job-id`（且未设 env）直接 `ValueError` 退出，不会静默回退到中文目录名。

---

## 核心设计

### 1. 位置表 + 倒序招呼（彻底解决 BOSS 动态换卡）

```
list DOM 一次 evaluate 扫全（先滚到底触发懒加载 → 滚回顶取绝对坐标）
        ↓
state/geek_positions.json（候选人 → {doc_y, doc_x} 映射）
        ↓
按 doc_y 降序招呼（先招呼底部的人）
        ↓
每次招呼：frame.evaluate('button.click()') 直接调 DOM click
```

**为什么必须倒序？** BOSS list 不是静态的——招呼完一个人，BOSS 会从底部 append 新人。中部以上候选人 doc_y 不变，底部已招呼的人已经从 list 移除。所以**先招呼底部，再招呼上方**，让 BOSS 的"插入新人"动作不影响已招呼的人的位置。

### 2. 不再 page.mouse.click 算坐标（根除"打开简历详情"）

旧版用 `page.mouse.click(page_x, page_y)` 命中按钮 —— 但 `iframe_box.x + btn.x + btn.w/2` 这个 page 坐标可能**落在 li card-item 边缘外的某个 div 上**，那个 div 有 click handler → 触发"打开候选人简历详情"。**这就是用户报告的"老是打开在线简历"的根因**。

新版完全不走 page.mouse.click：

```python
# 直接 evaluate 调 button.click() —— 走 DOM 自带的事件流
frame.evaluate(r"""(idx) => {
    const all = document.querySelectorAll('button.btn-greet');
    if (all[idx] && (all[idx].textContent||'').trim() === '打招呼') {
        all[idx].click();   # ← 走 button DOM 自己的事件流
        return true;
    }
    return false;
}""", btn_idx)
```

走 button 自己 `.click()` —— 触发 BOSS Vue 的 click handler，根本不经过坐标 → 不会命中错位置。

### 3. 验证选择器（BOSS 招呼成功后 button class 变了）

```javascript
// ❌ 错（找不到）
document.querySelectorAll('button.btn-greet')

// ✅ 对（class 已变成 btn-continue）
document.querySelectorAll('button[class*="btn-continue"], button.btn-greet')
```

BOSS 招呼成功后 button class 从 `btn btn-greet` → `btn btn-continue btn-outline`，text 从"打招呼" → "继续沟通"。

### 4. 容差 dy_tol=220（适应 list 状态变化）

```python
# 找最近 name 精确匹配的 li（dy_tol=220 ≈ 1 个 li 高度）
for li in lis:
    if clean !== name: continue
    ...
    if dy_diff <= 220 && dy_diff < best_dy_diff:
        best_li = li
```

BOSS list 状态会变，存的位置可能飘移 100+ px。如果 `best_dy_diff > 220` 直接放弃招呼（避免点错附近的人）。

### 5. 招呼前预检 modal/drawer

```python
# 0) 招呼前预检 page + iframe 内的阻挡层
for sel in ['.resume-detail-wrap', '.geek-resume',          # 简历详情 drawer
            '[class*="modal"]', '[class*="dialog"]', ...]:  # 通用 modal
    ...
if found:
    page.keyboard.press('Escape')  # 先按 Esc
    frame.evaluate('找 close 按钮 → click')
```

之前残留的"已向牛人发送招呼" dialog 或简历详情 drawer 会挡住下一个按钮。代码自动预检 + 关闭。

### 6. dialog 关闭用 element.click()

```python
# ❌ 错（locator.click 在 button>=468 时超时）
page.locator('button').nth(467).click()

# ✅ 对（直接 evaluate 调 .click()）
frame.evaluate(r"""() => {
    for (const b of document.querySelectorAll('button')) {
        if ((b.textContent||'').trim() === '知道了' && b.offsetWidth > 0) {
            b.click();
            return;
        }
    }
}""")
```

---

## 输出与状态

### 落盘文件

```
<工作区根>/<岗位名>/runs/<run_id>/process/
└── greet_log.json       # 本次打招呼详细日志
```

`greet_log.json` 示例：

```json
{
  "job": "结构设计、研发工程师",
  "run_id": "2026-01-01_000000",
  "score_threshold": 0,
  "source_run_id": "2026-01-01_000001",
  "summary": {
    "greeted": 2, "clicked_unverified": 0, "not_found": 0, "total": 2
  },
  "results": [
    {
      "name": "候选人甲",
      "score": 0.0, "tier": "from-pool",
      "found": true, "clicked": true, "verified": true, "dialog_closed": true,
      "status": "greeted",
      "school": "...", "work_years": "...", "current_role": "..."
    }
  ]
}
```

### status 含义

| status | 含义 |
|--------|------|
| `greeted` | ✅ 按钮变 "继续沟通"，打招呼成功 |
| `clicked_unverified` | ⚠ 点击了但验证失败（可能 BOSS 频率限制 / list 已重排） |
| `not_found` | 候选人不在当前 list（已招呼过 / 被 BOSS 排除） |

---

## 工作区路径约定（新设计 · 2026-07-29+）

```
<工作区根>/
├── jobs.json                               # JobRegistry：encryptJobId → {name, company}
└── <encryptJobId>/                         # 目录名 = BOSS 的 encryptJobId
    ├── state/
    │   ├── candidate_pool.json              # 累计候选人
    │   ├── resumes_master.json              # 累计简历
    │   ├── download_state.json              # 下载状态
    │   ├── scored_state.json                # 已评分状态
    │   └── geek_positions.json              # 候选人 doc_y/doc_x 映射（本 Skill 维护）
    └── runs/
        └── <run_id>/
            └── process/
                └── greet_log.json           # 本 Skill 输出
```

`geek_positions.json` 跨 run 保留，但每次 `--scan-only` 或默认模式会刷新。

> 工作区根默认是 `~/Desktop/boss-hr-output`，可通过 `BOSS_HR_OUTPUT_DIR` 环境变量改。
> 岗位目录名 = `encryptJobId`，通过 `--encrypt-job-id` 显式传入。

---

## 与 boss-hr-auto 的关系

`boss-hr-auto` 编排的 5 步流程（JD → 下载 → 评分 → HTML 报告 → 打招呼）的 Step 5 即调本 Skill。**主流程跑完会自动招呼**，无需手动再跑一次。

```
boss-hr-auto (Step 1→5)
  └ Step 3: resume-screener 输出 screening_results.json（含 candidates[].total）
       ↓
boss-hr-greet（本 Skill，Step 5）
  └ 读 screening_results.json → 按 threshold 筛 → 倒序招呼
       ↓
runs/<run_id>/process/greet_log.json 落盘
```

---

## 已知限制

### 1. BOSS list 动态换卡

- 候选人打招呼 / 下载 / 拒过后会被 list 自动换掉
- 重新加载页面后 list 内容会变
- **解决**：扫描时按 name 精确匹配 + dy_tol=220 容差 + `not_found` 状态

### 2. BOSS list 5 列副本

每个候选人**横向 5 列副本**（`.card-item` 5 个副本，li.dx ∈ {174, 442, 710, 978, 1237}），`button.btn-greet` 总数 ≈ 候选人 × 5。但脚本只关心单个 li 的 button click（走 DOM 索引），不需要像旧版那样用 `li:has-text(name)` locator 锁定唯一卡片。

### 3. BOSS 打招呼频率限制

- 连续招呼 10+ 后，**部分 click 后按钮不变**（BOSS 频率保护）
- `clicked_unverified` 状态表示该次招呼需要重试
- **建议**：每次招呼间隔 3-6 秒，超过 10 人/批

### 4. iframe 弹窗 vs 主页面弹窗

"已向牛人发送招呼" dialog 可能出现在：
- iframe 内（多见）
- 主页面 body 上（少见，Vue transfer-dom）

代码两个都尝试找"知道了"按钮。

---

## 关键文件

| 路径 | 说明 |
|------|------|
| `boss-hr-greet/scripts/auto_greet.py` | 实现脚本（~730 行，**本 Skill 的唯一执行入口**） |
| `boss-hr-greet/SKILL.md` | 本文档 |
| `shared/output_manager.py` | `JobOutputManager` 路径管理（已支持 `BOSS_HR_OUTPUT_DIR` 环境变量） |
| `shared/human_interaction.py` | `human_move` 拟人鼠标移动 |

---

## 关联 Skill

- `boss-hr-auto`：5 步全流程（JD → 下载 → 评分 → HTML → 打招呼）
- `resume-screener`：输出 `screening_results.json`（打招呼的依据）
- `boss-recommend-downloader`：list + 下载（候选人来源）

完整流程：**list → 下载 → 评分 → 打招呼**。