#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件路径管理工具
所有 skill 必须使用此工具获取文件路径，确保输出结构统一

目录结构：
~/Desktop/boss-hr-output/<岗位名>/
├── state/                                  # 跨 run 保留，不带日期，不清空
│   ├── candidate_pool.json
│   ├── download_state.json
│   ├── resumes_master.json
│   └── collection_state.json
└── runs/
    └── 2026-07-27_083015/                  # 一次筛选任务
        ├── 2026-07-27_083015_<岗位名>_简历筛选报告.html
        └── process/
            ├── job_detail.json
            ├── recommend_geek_ids.json     # 本次新增候选人
            ├── new_resumes.json            # 本次新增简历
            ├── failed_resumes.json
            ├── screening_results.json
            ├── run_summary.json
            └── run_log.txt
"""
import os
import shutil
import json
from datetime import datetime
from typing import Optional

# 输出根目录（可通过 BOSS_HR_OUTPUT_DIR 环境变量覆盖，方便其他机器 / WSL / Linux 部署）
OUTPUT_ROOT = os.environ.get('BOSS_HR_OUTPUT_DIR') or os.path.expanduser('~/Desktop/boss-hr-output')

# 环境变量名（CLI 透传 + 兜底）
ENV_ENCRYPT_JOB_ID = 'BOSS_HR_ENCRYPT_JOB_ID'


def _make_run_id() -> str:
    """生成 run_id：YYYY-MM-DD_HHMMSS"""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def resolve_encrypt_job_id(cli_value: Optional[str] = None, *, allow_fallback: bool = True) -> Optional[str]:
    """解析 encrypt_job_id：CLI 透传 > 环境变量 > None。

    Args:
        cli_value:        CLI --encrypt-job-id 的值（None=未传）
        allow_fallback:   True=允许走旧逻辑（用 job_name 当目录名）；
                          False=取不到就 raise（强制新设计）

    优先级：
        1) CLI 显式传 (cli_value)
        2) 环境变量 BOSS_HR_ENCRYPT_JOB_ID
        3) jobs.json by_job_name 反查（仅 allow_fallback=True）

    Raises:
        ValueError:  allow_fallback=False 且取不到时
    """
    if cli_value:
        return cli_value
    env_v = os.environ.get(ENV_ENCRYPT_JOB_ID)
    if env_v:
        return env_v
    if allow_fallback:
        return None
    raise ValueError(
        f"缺少 encrypt_job_id。\n"
        f"  新设计要求：目录名 = encryptJobId（不可变 ID，与候选人 geek_id 同源）。\n"
        f"  解决：在 CLI 传 --encrypt-job-id <ENCRYPT_JOB_ID>，"
        f"或设置环境变量 {ENV_ENCRYPT_JOB_ID}。\n"
        f"  不允许静默回退到旧逻辑（job_name 当目录名）。"
    )


class JobOutputManager:
    """岗位输出管理器 - 所有 skill 共用

    路径定位策略（2026-07-29）：
    - **优先用 `encrypt_job_id` 作目录名**（不可变 ID，与候选人 geek_id 同源）
    - `job_name` 仅作 metadata（写入 jobs.json，供人类查看）
    - 旧调用（只传 job_name）仍可用 —— 自动从 jobs.json 反查或生成 placeholder
    """

    def __init__(self, job_name=None, run_id=None, lazy=False, encrypt_job_id=None):
        """
        Args:
            job_name:        岗位名称（人类可读）。可空 —— 只用 encrypt_job_id 也能跑
            encrypt_job_id:  BOSS 的 encryptJobId（推荐）。优先用于目录命名
            run_id:          本次 run 的 ID。**必填**（2026-07-30 重构：run_id 是数据边界，
                            禁止再从 state/current_run.json 自动沿用）
            lazy:            默认 False（创建 state/ 和 runs/）

        Raises:
            ValueError: run_id 为空（必须显式传 run_id）
        """
        from job_registry import JobRegistry, resolve_job_dir
        self.encrypt_job_id = encrypt_job_id

        # 路径定位：encrypt_job_id 优先
        if encrypt_job_id:
            self.job_dir = resolve_job_dir(encrypt_job_id, name=job_name)
            # 注册 metadata（job_name 作人类可读名字）
            if job_name:
                JobRegistry().register(encrypt_job_id, name=job_name)
            else:
                meta = JobRegistry().get(encrypt_job_id)
                job_name = (meta or {}).get("name") or encrypt_job_id
        else:
            # 旧调用：用 job_name 作目录名（兼容模式 —— 不强求迁移）
            job_name = job_name or "unknown_job"
            self.job_dir = os.path.join(OUTPUT_ROOT, job_name)
            # 尝试反查 encrypt_job_id
            meta = JobRegistry().by_name(job_name)
            if meta:
                self.encrypt_job_id = meta.get("encrypt_job_id")

        self.job_name = job_name
        self.state_dir = os.path.join(self.job_dir, 'state')
        self.runs_dir = os.path.join(self.job_dir, 'runs')

        # run_id 解析（2026-07-30 重构）：run_id 是数据边界，必须显式传
        # —— 但 lazy=True 时只读路径（state_dir / runs_dir），不读 run_dir，
        # 这种情况下允许不传 run_id（JobResumeStore 跨 run 去重时使用）。
        if not run_id and not lazy:
            raise ValueError(
                "JobOutputManager.run_id 是必填参数（2026-07-30 重构）。"
                "新任务先调 create_new_run() 拿到 run_id；继续任务显式传 run_id。"
                "禁止从 state/current_run.json 自动沿用 —— 那是智能体偷懒入口。"
            )
        self.run_id = run_id
        if run_id:
            self.run_dir = os.path.join(self.runs_dir, self.run_id)
            self.process_dir = os.path.join(self.run_dir, 'process')
        else:
            self.run_dir = None
            self.process_dir = None

        # 自动创建（默认）
        if not lazy:
            os.makedirs(self.state_dir, exist_ok=True)
            os.makedirs(self.runs_dir, exist_ok=True)
            self.ensure_run_dir()

    # 注：2026-07-30 之前的方法 _resolve_run_id_from_state / _persist_current_run_id
    #     已被彻底删除 —— state/current_run.json 不再读写。

    def ensure_run_dir(self) -> None:
        """显式创建本次 run 的 run_dir / process_dir（懒模式下的兜底）。"""
        os.makedirs(self.run_dir, exist_ok=True)
        os.makedirs(self.process_dir, exist_ok=True)

    # ============ 最终报告路径（HTML 在 run 目录下，文件名带 run_id）============
    @property
    def report_path(self):
        """HTML 报告（同 run 内固定名，跨 run 不覆盖）

        文件名用英文 ID 风格 —— 不可变 ID 已经在目录结构里
        （encrypt_job_id → job_dir，run_id → run_dir），文件名再加
        中文会让"目录/文件名都走不可变 ID"的统一原则破洞。
        同 run 重新生成报告会被覆盖，跨 run 由 run_id 区分。
        """
        return os.path.join(self.run_dir, f'{self.run_id}_screening_report.html')

    # ============ 过程文件路径（全部在 runs/<run_id>/process/） ============
    @property
    def jd_path(self):
        return os.path.join(self.process_dir, 'job_detail.json')

    @property
    def recommend_geek_ids_path(self):
        """本次新增候选人（仅本次 run 滚到的）"""
        return os.path.join(self.process_dir, 'recommend_geek_ids.json')

    @property
    def new_resumes_path(self):
        """本次新增简历（仅本次 run 下载成功的）"""
        return os.path.join(self.process_dir, 'new_resumes.json')

    @property
    def failed_resumes_path(self):
        return os.path.join(self.process_dir, 'failed_resumes.json')

    @property
    def screening_results_path(self):
        return os.path.join(self.process_dir, 'screening_results.json')

    @property
    def run_summary_path(self):
        return os.path.join(self.process_dir, 'run_summary.json')

    @property
    def run_log_path(self):
        return os.path.join(self.process_dir, 'run_log.txt')

    # ============ 状态文件路径（state/，跨 run 保留） ============
    @property
    def candidate_pool_path(self):
        return os.path.join(self.state_dir, 'candidate_pool.json')

    @property
    def download_state_path(self):
        return os.path.join(self.state_dir, 'download_state.json')

    @property
    def resumes_master_path(self):
        return os.path.join(self.state_dir, 'resumes_master.json')

    @property
    def collection_state_path(self):
        return os.path.join(self.state_dir, 'collection_state.json')

    # ============ 旧路径（保留兼容：让旧脚本仍能 import）============
    @property
    def resumes_path(self):
        """兼容：旧代码找的 test_resumes.json 现在指向累计 resume master"""
        return self.resumes_master_path

    # ============ 通用工具 ============
    def get_process_path(self, filename):
        return os.path.join(self.process_dir, filename)

    def get_run_path(self, filename):
        return os.path.join(self.run_dir, filename)

    def get_state_path(self, filename):
        return os.path.join(self.state_dir, filename)

    def cleanup_temp_scripts(self):
        """保留兼容：实际临时脚本位于 process/ 下，调用方自行管理"""
        return  # no-op: 旧实现清理 ~/Desktop/ 路径错误，已禁用

    @staticmethod
    def cleanup_empty_runs(job_name=None, runs_dir=None, dry_run=False, trash_bin=None,
                           keep_without_report=False):
        """清理"无产物 / 孤儿"的 run 目录。

        默认严格：
        - 一个 run 目录被视为有效 ⇔ 它的 run_dir 顶层存在 HTML 报告。
        - 仅有 process/ 里的中间 json 是不够的（避免「Step1/2 跑了一半」或
          「脚本崩溃 / Ctrl+C」留下来的孤儿目录）。
        - 想要旧行为（process 里有文件就算有效），传 keep_without_report=True。

        Args:
            job_name:  岗位名（与 runs_dir 二选一）
            runs_dir:  直接指定 runs/ 绝对路径（跨岗位批量清理时用）
            dry_run:   只扫描不删
            trash_bin: 删除命令（默认 'mavis-trash'，可换 'Remove-Item -Recurse'）
            keep_without_report:  True 时把"有 process 文件但没报告"也算有效 run

        Returns:
            dict {trashed: [paths], skipped_busy: [paths], scanned: int, runs_dir}
        """
        if runs_dir is None:
            if job_name is None:
                raise ValueError("cleanup_empty_runs: 必须给 job_name 或 runs_dir")
            runs_dir = os.path.join(OUTPUT_ROOT, job_name, 'runs')
        if not os.path.isdir(runs_dir):
            return {"trashed": [], "skipped_busy": [], "scanned": 0, "runs_dir": runs_dir}

        bin_cmd = trash_bin or "mavis-trash"

        def _do_remove(rd: str) -> bool:
            """跨平台删除一个 run 目录。

            优先级：
              1) trash_bin 是函数调用（trash_bin.callable）→ 调用；
              2) Windows 下 mavis-trash / Remove-Item 都经常不存在，
                 直接用 shutil.rmtree 更可靠；
              3) 其他平台按 bin_cmd shell 命令。
            """
            import shutil as _sh
            if callable(trash_bin):
                try:
                    return bool(trash_bin(rd))
                except Exception:
                    pass
            if os.name == "nt":
                try:
                    _sh.rmtree(rd)
                    return True
                except Exception:
                    return False
            subprocess.run(f'{bin_cmd} "{rd}"', shell=True, check=False)
            return not os.path.isdir(rd)

        def _has_html_report(rd):
            """run_dir 顶层有没有 HTML 报告（只看顶层 .html 文件）。"""
            if not os.path.isdir(rd):
                return False
            for f in os.listdir(rd):
                if f.startswith("."):
                    continue
                if f.lower().endswith(".html") and os.path.isfile(os.path.join(rd, f)):
                    return True
            return False

        def _has_files(d):
            if not os.path.isdir(d):
                return False
            for f in os.listdir(d):
                if f.startswith("."):
                    continue
                if os.path.isfile(os.path.join(d, f)):
                    return True
            return False

        def _is_valid_run(rd):
            """严格判定：有 HTML 报告 = 有效。
            兼容模式（keep_without_report=True）：有 HTML 报告 或 process/ 里有文件。"""
            if _has_html_report(rd):
                return True
            if keep_without_report and _has_files(os.path.join(rd, "process")):
                return True
            return False

        result = {"trashed": [], "skipped_busy": [], "scanned": 0, "runs_dir": runs_dir}
        for name in sorted(os.listdir(runs_dir)):
            rd = os.path.join(runs_dir, name)
            if not os.path.isdir(rd):
                continue
            result["scanned"] += 1
            if not _is_valid_run(rd):
                if dry_run:
                    result["trashed"].append(rd)
                else:
                    if _do_remove(rd):
                        result["trashed"].append(rd)
                    else:
                        result["skipped_busy"].append(rd)
            else:
                result["skipped_busy"].append(rd)
        return result

    def prune_if_empty(self):
        """如果当前 run_dir 没有 HTML 报告（且 process 也空），删除整个 run_dir。

        设计意图：在每个 Step 脚本的 `finally` 里调用 —
        即使脚本中途崩溃 / Ctrl+C，也不会留下「空 process/ 单文件」孤儿。
        与 cleanup_empty_runs 不同的是：单实例方法，操作的是 self.run_dir。
        """
        if not os.path.isdir(self.run_dir):
            return False
        # 任何位置有 HTML 报告 → 保留
        for f in os.listdir(self.run_dir):
            if f.startswith("."):
                continue
            full = os.path.join(self.run_dir, f)
            if os.path.isfile(full) and f.lower().endswith(".html"):
                return False
        # 没报告，删
        try:
            shutil.rmtree(self.run_dir)
            return True
        except OSError:
            return False


# 使用示例
if __name__ == '__main__':
    out = JobOutputManager('机械工程师')
    print(f'run_id       ：{out.run_id}')
    print(f'job_dir      ：{out.job_dir}')
    print(f'state_dir    ：{out.state_dir}')
    print(f'run_dir      ：{out.run_dir}')
    print(f'process_dir  ：{out.process_dir}')
    print(f'报告路径      ：{out.report_path}')
    print(f'JD 路径       ：{out.jd_path}')
    print(f'本次简历路径  ：{out.new_resumes_path}')
    print(f'累计简历路径  ：{out.resumes_master_path}')
