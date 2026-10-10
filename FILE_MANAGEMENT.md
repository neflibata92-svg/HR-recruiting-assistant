# boss-hr-agent-toolkit 文件管理规范

## 📁 统一输出结构

所有 skill 产生的文件必须遵循以下结构：

```
~/Desktop/boss-hr-output/                    # 所有输出放这里
└── <岗位名>/                                  # 按岗位名建子文件夹
    ├── state/                                 # 跨 run 累计，不覆盖
    │   ├── candidate_pool.json
    │   ├── download_state.json
    │   ├── resumes_master.json
    │   ├── scored_state.json                  # 已评分记录（跨 run 评分去重）
    │   ├── geek_positions.json
    └── runs/
        └── <run_id>/                          # 一次筛选任务
            ├── <run_id>_<岗位名>_简历筛选报告.html
            └── process/
                ├── job_detail.json
                ├── recommend_geek_ids.json
                ├── new_resumes.json
                ├── _llm_scores.json
                ├── screening_results.json
                ├── greet_log.json
                └── failed_resumes.json
```

## 🚨 重要规则

### 1. 禁止在桌面散落文件
- ❌ 错误：`~/Desktop/test_resumes.json`
- ✅ 正确：`~/Desktop/boss-hr-output/机械工程师/process/test_resumes.json`

### 2. HTML 报告放岗位文件夹根目录
- ❌ 错误：`~/Desktop/boss-hr-output/机械工程师/process/报告.html`
- ✅ 正确：`~/Desktop/boss-hr-output/机械工程师/机械工程师_简历筛选报告.html`

### 3. 中间数据放 process/ 子文件夹
- 所有 JSON 数据文件
- 所有临时日志文件
- 所有中间计算结果

### 4. 临时 Python 脚本任务结束后删除
- ❌ 错误：任务完成后 `generate_report.py` 还留在桌面
- ✅ 正确：调用 `output.cleanup_temp_scripts()` 清理

### 5. 复用 skill 内已有的 Python 脚本
- ❌ 错误：智能体重新写一个 `generate_report.py`
- ✅ 正确：使用 skill 的 `scripts/` 文件夹中已有的脚本

### 6. 岗位文件夹不存在时自动创建
- 不要询问用户，直接创建
- 使用 `os.makedirs(JOB_DIR, exist_ok=True)`

## 🔧 使用方法

### 在 Python 脚本中

```python
import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from output_manager import JobOutputManager

# 初始化输出管理器
output = JobOutputManager('机械工程师')

# 获取文件路径
print(output.report_path)           # HTML 报告路径
print(output.jd_path)               # JD 数据路径
print(output.resumes_path)          # 简历数据路径
print(output.recommend_geek_ids_path)  # 候选人 ID 路径

# 保存数据
with open(output.resumes_path, 'w', encoding='utf-8') as f:
    json.dump(resumes, f, ensure_ascii=False, indent=2)

# 任务结束后清理临时脚本
output.cleanup_temp_scripts()
```

### 在 Skill 文档中

所有 skill 的 SKILL.md 必须包含：

```markdown
### 输出文件

本 skill 产生的文件：
- `<岗位名>_xxx.html` → `~/Desktop/boss-hr-output/<岗位名>/`
- `xxx.json` → `~/Desktop/boss-hr-output/<岗位名>/process/`

使用 `output_manager.py` 获取文件路径，不要硬编码路径。
```

##  已有 Python 脚本清单

以下脚本位于各 skill 的 `scripts/` 文件夹中，**必须复用，禁止重复造轮子**：

### boss-recommend-downloader/scripts/
- `recommend_list.py` — 获取推荐牛人候选人列表
- `recommend_download.py` — 批量获取完整简历
- `run_all.py` — 一键运行全流程

### boss-hr-greet/scripts/
- `auto_greet.py` — 高分候选人自动打招呼（位置表 + 倒序招呼）

### shared/
- `output_manager.py` — 统一文件路径管理（所有 skill 共用）
- `run_orchestrator.py` — 跨 Step run_id 编排（让所有产物落在同一 runs/<run_id>/）
- `job_resume_store.py` — 候选人键 + 三态状态读写 + 简历合并

## 🧹 清理桌面散落文件

如果桌面已经有散落文件，运行以下命令清理：

```python
import os

desktop = os.path.expanduser('~/Desktop')
temp_files = [
    'generate_report.py',
    'generate_report_corrected.py',
    'job_detail.json',
    'recommend_geek_ids.json',
    'screening_results.json',
    'screening_results_corrected.json',
    'test_resumes.json',
    'schools.txt',
    'resume_preview.txt',
    'boss_api_data.json',
    'boss_recommend_page.png'
]

for f in temp_files:
    path = os.path.join(desktop, f)
    if os.path.exists(path):
        os.remove(path)
        print(f'已删除：{f}')
```

### 清理 toolkit 根目录的临时诊断脚本

排查过程中可能落在 toolkit 根目录的 `_diag_*.py` 临时脚本（不属于任何 skill，不该留）。运行：

```python
import os, glob

toolkit_root = os.path.dirname(os.path.abspath(__file__))
patterns = ['_diag_*.py', '_tmp_*.py']

removed = []
for pattern in patterns:
    for path in glob.glob(os.path.join(toolkit_root, pattern)):
        os.remove(path)
        removed.append(os.path.basename(path))

if removed:
    print('已删除：', removed)
else:
    print('toolkit 根目录无临时诊断脚本')
```

## 📖 示例：完整工作流

> **没有一把梭脚本。** `boss-hr-auto` 是纯文档 Skill，由智能体按 SKILL.md 的 Step 顺序
> 依次调用各子 Skill 的脚本。**每一步都必须显式传同一个 `--run-id`**，否则产物会散落到
> 不同 run 目录（2026-07-30 重构：run_id 是数据边界，必须显式传 `--run-id`；不再自动沿用）。

```bash
# 0. 先开 run_id（所有 Step 共用这一个）
RUN_ID=$(python -X utf8 -c "
import sys; sys.path.insert(0,'shared')
from run_orchestrator import RunOrchestrator
print(RunOrchestrator('机械工程师').create_new_run())
")

# 1. Step 1 提取 JD
python -X utf8 boss-job-detail/scripts/boss_jd.py "<encryptJobId>" --run-id "$RUN_ID"

# 2. Step 2 候选人列表 + 下载简历
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "机械工程师" --run-id "$RUN_ID"
python -X utf8 boss-recommend-downloader/scripts/recommend_download.py \
  --job-name "机械工程师" --run-id "$RUN_ID" --max 25

# 3. Step 3 评分（净化层 → LLM 落盘 → 合并 → 收尾）
#    3a) 净化：new_resumes.json → scoring/inputs/candidate_<geek_id>.json + manifest.json
python -X utf8 resume-screener/scripts/prepare_scoring_inputs.py \
  --job-name "机械工程师" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"
#    3b) LLM 智能体：读 scoring/inputs/，逐份评，每评一份立即落盘 scoring/outputs/candidate_<geek_id>.json
#        （不在 process/ 落 _split_N.json / _llm_1.json 等临时分片文件；outputs/ 是唯一落盘点）
#    3c) 合并：scoring/outputs/ → _llm_scores.json（幂等可重跑）
python -X utf8 resume-screener/scripts/collect_llm_scores.py \
  --job-name "机械工程师" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"
#    3d) 收尾：edu 校准 + 加权 + tier 判定 → screening_results.json
python -X utf8 resume-screener/scripts/score_resumes.py \
  --job-name "机械工程师" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"

# 4. Step 4 生成报告
python -X utf8 html-report/scripts/generate_html_report.py \
  --input  "runs/$RUN_ID/process/screening_results.json" \
  --output "runs/$RUN_ID/${RUN_ID}_机械工程师_简历筛选报告.html"

# 5. Step 5 打招呼
python -X utf8 boss-hr-greet/scripts/auto_greet.py \
  --job-name "机械工程师" --run-id "$RUN_ID"

# 中间产物
# - process/job_detail.json         Step 1 boss_jd.py
# - process/recommend_geek_ids.json Step 2 recommend_list.py
# - process/new_resumes.json        Step 2 recommend_download.py
# - process/_llm_scores.json        Step 3 LLM agent 评 4 维度
# - process/screening_results.json  Step 3 score_resumes.py
# - <run_id>_<岗位>_简历筛选报告.html  Step 4
# - process/greet_log.json          Step 5 auto_greet.py
```

最终交付给用户的只有一份 HTML 报告 + 一份打招呼日志（greet_log.json），其他都是留痕查阅的过程文件。
