"""跨 run 数据边界编排器 — run_id 是本次任务的数据边界。

设计原则（2026-07-30 重构）：
  - 新任务永远 create_new_run()，禁止任何形式的「自动复用历史 run」。
  - 继续某个旧任务必须显式传 run_id，调用 bind_existing_run(run_id)。
  - 每个 run 拥有独立的 runs/<run_id>/run.json，记录：
        confirmed 标志位（用户是否已确认）、steps_done、finished 等。
  - 不再有 state/current_run.json（彻底废弃）。

run.json 结构（每个 run 独立一份）：
    {
      "run_id": "2026-07-30_103000",
      "encrypt_job_id": "...",
      "started_at": "...",
      "confirmed": false,            # 用户在 BOSS 调整完筛选条件后调 confirm_run.py 切 true
      "user_confirmed_at": null,
      "steps_done": ["jd","download",...],
      "last_step": "...",
      "last_step_at": "...",
      "finished": false,
      "finished_at": null,
    }

行为：
    create_new_run()                       — 无条件创建新 run_id
    bind_existing_run(run_id)              — 必传 run_id，校验 run_dir + encryptJobId
    init_run_state(run_id)                 — 写 run.json（confirmed=false）
    confirm_run(run_id)                    — confirmed=true（供 confirm_run.py 调用）
    is_confirmed(run_id) -> bool           — Step 2 守卫
    mark_done(step, run_id)                — 写步骤
    finish(run_id)                         — 标记结束

旧接口（已废弃，调用即抛 RuntimeError）：
    bind_or_create()  ← 任何生产代码不应再调用
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime
from typing import Optional

from output_manager import JobOutputManager, resolve_encrypt_job_id

COLLECTION_STATE_FILENAME = "collection_state.json"  # 旧版兼容：保留以备其他脚本读取

# 退出码约定（智能体据此识别停下原因）
EXIT_CODE_AWAITING_CONFIRMATION = 20   # confirmed != true
EXIT_CODE_MISSING_RUN_ID = 22
EXIT_CODE_RUN_NOT_FOUND = 23
EXIT_CODE_RUN_JOB_MISMATCH = 24


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class RunOrchestrator:
    """跨 run 数据边界编排器。"""

    RUN_FILENAME = "run.json"

    def __init__(self, job_name: str, encrypt_job_id: Optional[str] = None,
                 run_id: Optional[str] = None):
        """
        Args:
            job_name:        岗位名
            encrypt_job_id:  BOSS encryptJobId
            run_id:          可选。如果传，会立刻实例化 JobOutputManager；
                            不传也能调 create_new_run / bind_existing_run，
                            后续 _mgr 会延迟创建。
        """
        self.job_name = job_name
        self.encrypt_job_id = resolve_encrypt_job_id(encrypt_job_id)
        # 延迟实例化 mgr —— 避免在没有 run_id 时就要求它必须传 run_id
        self._mgr: Optional[JobOutputManager] = None
        if run_id:
            self._mgr = self._make_mgr(run_id)
        self.collection_path = None  # 兼容旧代码（当前已不使用）

    def _make_mgr(self, run_id: str) -> JobOutputManager:
        return JobOutputManager(
            job_name=self.job_name,
            encrypt_job_id=self.encrypt_job_id,
            run_id=run_id,
            lazy=True,
        )

    @property
    def _mgr_lazy(self) -> JobOutputManager:
        """延迟返回 mgr（用 __placeholder__ 仅为了取 runs_dir 等路径常量）。

        单一来源：所有路径计算走 _mgr.runs_dir，run.json 路径走
        _ensure_run_dir_state → self.RUN_FILENAME。
        """
        if self._mgr is None:
            # __placeholder__ 仅用于触发 JobOutputManager 路径解析
            self._mgr = self._make_mgr("__placeholder__")
        return self._mgr

    # ---------- 内部：读写 runs/<run_id>/run.json ----------
    def _ensure_run_dir_state(self, run_id: str) -> str:
        """返回 runs/<run_id>/run.json 路径，必要时建目录。"""
        mgr = self._mgr_lazy
        run_dir = os.path.join(mgr.runs_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        return os.path.join(run_dir, self.RUN_FILENAME)

    def _load_run(self, run_id: str) -> dict:
        path = self._ensure_run_dir_state(run_id)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_run(self, run_id: str, state: dict) -> None:
        path = self._ensure_run_dir_state(run_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _gen_run_id(self) -> str:
        """生成新 run_id。同秒内已存在则追加 _2/_3/... 后缀。"""
        base = time.strftime("%Y-%m-%d_%H%M%S")
        candidate = base
        n = 2
        runs_dir = self._mgr_lazy.runs_dir
        os.makedirs(runs_dir, exist_ok=True)
        while os.path.isdir(os.path.join(runs_dir, candidate)):
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    # ---------- 旧接口（已废弃，调用即报错）----------
    def bind_or_create(self, *args, **kwargs):
        """已废弃（2026-07-30）。任何生产代码都不应再调用。

        调用即抛 RuntimeError，强制改用 create_new_run() / bind_existing_run(run_id)。
        """
        raise RuntimeError(
            "bind_or_create() 已废弃。"
            "新任务请调 create_new_run()；继续任务请调 bind_existing_run(run_id)。"
        )

    # ---------- 关键入口 ----------
    def create_new_run(self) -> str:
        """无条件创建新 run。每次调用都返回全新 run_id。"""
        new_id = self._gen_run_id()
        mgr = self._mgr_lazy
        os.makedirs(os.path.join(mgr.runs_dir, new_id), exist_ok=True)
        return new_id

    def init_run_state(self, run_id: str) -> None:
        """初始化 runs/<run_id>/run.json（confirmed=false）。"""
        if not run_id:
            raise ValueError("init_run_state 必须显式传 run_id")
        cur = self._load_run(run_id)
        cur["run_id"] = run_id
        cur["encrypt_job_id"] = self.encrypt_job_id
        cur["started_at"] = _now_str()
        cur["confirmed"] = False
        cur["user_confirmed_at"] = None
        cur.setdefault("steps_done", [])
        cur["finished"] = False
        cur["finished_at"] = None
        self._save_run(run_id, cur)

    def bind_existing_run(self, run_id: Optional[str]) -> str:
        """绑定到一个已存在的 run。run_id 必须显式传。

        Args:
            run_id: 已存在的 run 目录名（不含路径），如 "2026-07-30_103000"。

        Returns:
            str: 校验通过的 run_id（与入参相同；显式返回便于调用方链式赋值）。

        Raises:
            ValueError:        run_id 为空（缺少 --run-id）
            FileNotFoundError: run_id 对应目录不存在
            RuntimeError:      run_id 与当前 encrypt_job_id 不匹配

        行为：
          - 不读 current_run.json / latest_run.json
          - 校验 run_dir 存在 + job_detail.json 里 encryptJobId 一致
          - 校验失败抛异常；不创建新 run，不返回别的 run_id
        """
        if not run_id:
            raise ValueError(
                "缺少 --run-id。run_id 是数据边界，禁止自动选择历史 run。"
                "新任务必须先调 create_new_run()，旧任务必须显式传 --run-id。"
            )
        run_dir = os.path.join(self._mgr_lazy.runs_dir, run_id)
        if not os.path.isdir(run_dir):
            raise FileNotFoundError(
                f"run_id={run_id} 在岗位目录下不存在（{run_dir}）。"
                "可能是别岗位的 run_id，或拼写错误。"
            )
        # 校验 encrypt_job_id 匹配
        jd_path = os.path.join(run_dir, "process", "job_detail.json")
        if os.path.exists(jd_path):
            try:
                with open(jd_path, "r", encoding="utf-8") as f:
                    jd = json.load(f)
                jd_eid = jd.get("encryptJobId") or jd.get("job_id") or ""
                if jd_eid and self.encrypt_job_id and jd_eid != self.encrypt_job_id:
                    raise RuntimeError(
                        f"run_id={run_id} 的 encryptJobId={jd_eid} "
                        f"与当前岗位的 encryptJobId={self.encrypt_job_id} 不匹配。"
                    )
            except (ValueError, RuntimeError):
                raise
            except Exception:
                pass
        return run_id

    # ---------- 用户确认 ----------
    def is_confirmed(self, run_id: str) -> bool:
        """返回当前 run 的 confirmed 标志位。Step 2 守卫。"""
        if not run_id:
            return False
        cur = self._load_run(run_id)
        return cur.get("confirmed") is True

    def confirm_run(self, run_id: str) -> None:
        """把 confirmed 切到 true（用户回复『继续』后调用）。"""
        if not run_id:
            raise ValueError("confirm_run 必须显式传 run_id")
        cur = self._load_run(run_id)
        cur["run_id"] = run_id
        cur["confirmed"] = True
        cur["user_confirmed_at"] = _now_str()
        self._save_run(run_id, cur)

    # ---------- 步骤标记 / 结束 ----------
    def mark_done(self, step: str, run_id: str) -> None:
        """标记某 step 完成。run_id 必填。"""
        if not run_id:
            raise ValueError("mark_done 必须显式传 run_id")
        cur = self._load_run(run_id)
        cur["run_id"] = run_id
        cur.setdefault("steps_done", [])
        if step not in cur["steps_done"]:
            cur["steps_done"].append(step)
        cur["last_step"] = step
        cur["last_step_at"] = _now_str()
        self._save_run(run_id, cur)

    def finish(self, run_id: str) -> None:
        """标记整个 run 结束。run_id 必填。"""
        if not run_id:
            raise ValueError("finish 必须显式传 run_id")
        cur = self._load_run(run_id)
        cur["run_id"] = run_id
        cur["finished"] = True
        cur["finished_at"] = _now_str()
        self._save_run(run_id, cur)