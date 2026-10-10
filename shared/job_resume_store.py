# -*- coding: utf-8 -*-
"""
岗位级简历存储库（去重 + 累计 + 原子保存）

设计核心：
- 唯一键：candidate_key = f"{encrypt_job_id}:{encrypt_geek_id}"
       禁止使用姓名（同名候选人无法区分）
- 状态分：
    success       永久跳过（下次 run 不再请求）
    failed        临时失败（下次 run 可重试）
    limit_hit     触发"今日查看上限"（立即停止整轮，不重试）
- 累计文件 4 个（放在 state/，跨 run 不覆盖）：
    candidate_pool.json    累计发现的候选人（去重）
    download_state.json    候选人级下载状态
    resumes_master.json    累计成功简历（含 _meta）
    collection_state.json  滚动/批次进度
- 写盘用临时文件 + os.replace 原子保存

调用方式：
    from job_resume_store import JobResumeStore
    store = JobResumeStore(job_name, encrypt_job_id)
    store.add_candidate(g)             # 收候选人
    store.untried_geeks()              # 待下载列表
    store.mark_success(geek_id, resume_obj)
    store.mark_failed(geek_id, reason)
    store.mark_limit_hit(geek_id)
    store.iter_resumes()               # 累计简历流
"""
import os
import json
import time
import tempfile


def candidate_key(encrypt_job_id: str, encrypt_geek_id: str) -> str:
    """岗位级唯一键（跨 run 去重）"""
    return f"{encrypt_job_id}:{encrypt_geek_id}"


def now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write_json(path: str, data) -> None:
    """原子写：写到同目录临时文件 → os.replace 替换。多进程/崩溃安全。"""
    path = str(path)
    dir_ = os.path.dirname(path)
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=dir_)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        raise


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


class JobResumeStore:
    """岗位级简历存储（state/ 下的 4 个文件）"""

    SCHEMA_VERSION = 1

    def __init__(self, job_name: str, encrypt_job_id: str = None):
        # 2026-07-29：CLI 推荐透传 encrypt_job_id，新设计目录名才准
        #            兼容模式：缺时从 jobs.json/legacy 反查（保留旧行为）
        from output_manager import resolve_encrypt_job_id
        self.job_name = job_name
        self.encrypt_job_id = (
            encrypt_job_id
            or resolve_encrypt_job_id()  # env 兜底
            or _load_legacy_job_id(job_name)  # 兼容旧逻辑
        )

        # state/ 目录（纯读操作 → lazy=True 不触发 runs/<run_id> 创建）
        from output_manager import JobOutputManager
        out = JobOutputManager(
            job_name,
            encrypt_job_id=self.encrypt_job_id,
            lazy=True,
        )
        self.state_dir = out.state_dir
        # state 目录读多于写，但仍要兜底存在
        os.makedirs(self.state_dir, exist_ok=True)

        self.candidate_pool_path = os.path.join(self.state_dir, "candidate_pool.json")
        self.download_state_path = os.path.join(self.state_dir, "download_state.json")
        self.resumes_master_path = os.path.join(self.state_dir, "resumes_master.json")
        self.collection_state_path = os.path.join(self.state_dir, "collection_state.json")
        self.scored_state_path = os.path.join(self.state_dir, "scored_state.json")

    # ---------- 候选人池 ----------
    def add_candidate(self, g: dict) -> bool:
        """加入候选池（去重）。返回 True=新加入，False=已存在。"""
        geek_id = g.get("encryptGeekId", "") or g.get("uid", "")
        if not geek_id:
            return False
        # 推断 job_id（如缺）
        job_id = self.encrypt_job_id or g.get("geekCard", {}).get("encryptJobId", "")
        if not job_id:
            return False
        key = candidate_key(job_id, geek_id)

        pool = _load_json(self.candidate_pool_path, {"schema_version": self.SCHEMA_VERSION,
                                                      "job_id": job_id, "items": {}})
        if not isinstance(pool, dict) or "items" not in pool:
            pool = {"schema_version": self.SCHEMA_VERSION, "job_id": job_id, "items": {}}
        pool["job_id"] = job_id
        if key in pool["items"]:
            return False
        pool["items"][key] = {
            "encrypt_job_id": job_id,
            "encrypt_geek_id": geek_id,
            "name": g.get("geekCard", {}).get("geekName", "") or g.get("name", ""),
            "first_seen_at": now_ts(),
            "raw": g,  # 保留原始推荐列表数据
        }
        _atomic_write_json(self.candidate_pool_path, pool)
        return True

    def add_candidates(self, geeks: list) -> int:
        """批量加入，返回新增数"""
        return sum(1 for g in geeks if self.add_candidate(g))

    def list_candidates(self) -> list:
        """返回候选池所有候选人（dict 列表，按 first_seen_at 顺序）"""
        pool = _load_json(self.candidate_pool_path, {"items": {}})
        items = pool.get("items", {})
        out = []
        for k, v in items.items():
            out.append(v.get("raw", v))
        return out

    def count_candidates(self) -> int:
        pool = _load_json(self.candidate_pool_path, {"items": {}})
        return len(pool.get("items", {}))

    # ---------- 下载状态 ----------
    def _load_state(self) -> dict:
        state = _load_json(self.download_state_path, {
            "schema_version": self.SCHEMA_VERSION,
            "job_id": self.encrypt_job_id,
            "items": {},
        })
        if not isinstance(state, dict) or "items" not in state:
            state = {"schema_version": self.SCHEMA_VERSION,
                     "job_id": self.encrypt_job_id, "items": {}}
        return state

    def _save_state(self, state: dict) -> None:
        # 强制写回顶层 job_id（download_state.json 顶层 job_id 可能是空字符串，
        # 覆盖一次后下游 _load_legacy_job_id 就能拿到）
        if self.encrypt_job_id:
            state["job_id"] = self.encrypt_job_id
        _atomic_write_json(self.download_state_path, state)

    def get_status(self, job_id: str, geek_id: str) -> str:
        """返回 success / failed / limit_hit / None"""
        key = candidate_key(job_id, geek_id)
        return self._load_state()["items"].get(key, {}).get("status")

    def mark_success(self, job_id: str, geek_id: str, run_id: str = None) -> None:
        key = candidate_key(job_id, geek_id)
        state = self._load_state()
        prev = state["items"].get(key, {})
        state["items"][key] = {
            "status": "success",
            "attempts": prev.get("attempts", 0) + 1,
            "downloaded_at": now_ts(),
            "first_run_id": prev.get("first_run_id") or run_id,
            "last_run_id": run_id,
            "last_error": None,
        }
        self._save_state(state)

    def mark_failed(self, job_id: str, geek_id: str, reason: str, run_id: str = None) -> None:
        """失败 = 临时，下次可重试"""
        key = candidate_key(job_id, geek_id)
        state = self._load_state()
        prev = state["items"].get(key, {})
        state["items"][key] = {
            "status": "failed",
            "attempts": prev.get("attempts", 0) + 1,
            "last_attempt_at": now_ts(),
            "last_run_id": run_id,
            "last_error": reason[:200] if reason else None,
        }
        self._save_state(state)

    def mark_limit_hit(self, job_id: str, geek_id: str, run_id: str = None) -> None:
        """触发"今日查看上限"——立即停止整轮，不重试"""
        key = candidate_key(job_id, geek_id)
        state = self._load_state()
        state["items"][key] = {
            "status": "limit_hit",
            "hitted_at": now_ts(),
            "last_run_id": run_id,
        }
        self._save_state(state)

    def untried_geeks(self, job_id: str = None) -> list:
        """返回从未尝试过 + 失败过的候选人（不含 success / limit_hit）"""
        job_id = job_id or self.encrypt_job_id
        state = self._load_state()
        candidates = self.list_candidates()
        out = []
        for g in candidates:
            gid = g.get("encryptGeekId", "") or g.get("uid", "")
            if not gid:
                continue
            if g.get("geekCard", {}).get("encryptJobId", "") and job_id != g["geekCard"]["encryptJobId"]:
                # 跨岗位数据混在池里，过滤掉
                continue
            status = self.get_status(job_id, gid)
            if status in (None, "failed"):
                out.append(g)
        return out

    def iter_successful_geeks(self) -> list:
        """返回所有 status=success 的候选人列表"""
        state = self._load_state()
        out = []
        for k, v in state["items"].items():
            if v.get("status") == "success":
                out.append({"candidate_key": k, **v})
        return out

    # ---------- 评分状态（跨 run 去重，避免同一候选人被反复评分） ----------
    def _load_scored(self) -> dict:
        state = _load_json(self.scored_state_path, {
            "schema_version": self.SCHEMA_VERSION,
            "job_id": self.encrypt_job_id,
            "items": {},
        })
        if not isinstance(state, dict) or "items" not in state:
            state = {"schema_version": self.SCHEMA_VERSION,
                     "job_id": self.encrypt_job_id, "items": {}}
        return state

    def _save_scored(self, state: dict) -> None:
        if self.encrypt_job_id:
            state["job_id"] = self.encrypt_job_id
        _atomic_write_json(self.scored_state_path, state)

    def is_scored(self, job_id: str, geek_id: str) -> bool:
        """该候选人是否已在历史某个 run 评过分"""
        key = candidate_key(job_id, geek_id)
        return key in self._load_scored()["items"]

    def get_score_record(self, job_id: str, geek_id: str) -> dict:
        """取历史评分记录（无则 None）"""
        key = candidate_key(job_id, geek_id)
        return self._load_scored()["items"].get(key)

    def mark_scored(self, job_id: str, geek_id: str, name: str = "",
                    total: float = None, tier: str = "", run_id: str = None) -> None:
        """记录一次评分结果。重复评分时保留首次 run_id，覆盖最新分数。"""
        key = candidate_key(job_id, geek_id)
        state = self._load_scored()
        prev = state["items"].get(key, {})
        state["items"][key] = {
            "name": name or prev.get("name", ""),
            "total": total,
            "tier": tier,
            "scored_at": now_ts(),
            "first_run_id": prev.get("first_run_id") or run_id,
            "last_run_id": run_id,
            "times": prev.get("times", 0) + 1,
        }
        self._save_scored(state)

    def scored_names(self) -> set:
        """历史已评分过的姓名集合。

        注意：仅供人工排查/兜底展示。判断"是否已评分"务必用 is_scored（按 ID），
        因为 BOSS 的"杨先生""吕女士"等匿名昵称会重名。
        """
        return {v.get("name", "") for v in self._load_scored()["items"].values() if v.get("name")}

    # ---------- 简历累计 ----------
    def save_resume(self, resume: dict, job_id: str, geek_id: str, run_id: str) -> bool:
        """保存成功简历（含 _meta）。返回 True=新加入，False=已存在。"""
        if not resume.get("ok"):
            return False
        key = candidate_key(job_id, geek_id)
        master = _load_json(self.resumes_master_path, {
            "schema_version": self.SCHEMA_VERSION,
            "job_id": job_id,
            "items": {},
        })
        if not isinstance(master, dict) or "items" not in master:
            master = {"schema_version": self.SCHEMA_VERSION, "job_id": job_id, "items": {}}
        if key in master["items"]:
            # 已存在：不覆盖（保留原 _meta）
            return False
        # 注入 _meta
        meta = {
            "candidate_key": key,
            "encrypt_job_id": job_id,
            "encrypt_geek_id": geek_id,
            "downloaded_at": now_ts(),
            "first_run_id": run_id,
        }
        # 简历对象也保留 name 字段（兼容）
        resume_copy = dict(resume)
        resume_copy["_meta"] = meta
        master["items"][key] = resume_copy
        master["job_id"] = job_id
        _atomic_write_json(self.resumes_master_path, master)
        return True

    def iter_resumes(self) -> list:
        """返回所有累计简历（list 形式）"""
        master = _load_json(self.resumes_master_path, {"items": {}})
        return list(master.get("items", {}).values())

    def count_resumes(self) -> int:
        master = _load_json(self.resumes_master_path, {"items": {}})
        return len(master.get("items", {}))

    # ---------- 滚动状态（保留旧 batch_state 字段兼容）----------
    def update_collection_state(self, **kwargs) -> None:
        state = _load_json(self.collection_state_path, {})
        state.update(kwargs)
        _atomic_write_json(self.collection_state_path, state)

    def get_collection_state(self) -> dict:
        return _load_json(self.collection_state_path, {})


def _load_legacy_job_id(job_name: str) -> str:
    """读 job_id。优先级：state 三件套顶层 job_id > 最新 run 的 jd_path > 空"""
    from output_manager import JobOutputManager
    out = JobOutputManager(job_name, lazy=True)

    # 1) state/ 下三个累计文件都顶层带 job_id（任一存在即可）
    for path in (out.candidate_pool_path, out.download_state_path, out.resumes_master_path):
        if os.path.exists(path):
            try:
                data = json.load(open(path, encoding="utf-8"))
                jid = data.get("job_id") or data.get("encryptJobId") or ""
                if jid:
                    return jid
            except Exception:
                pass

    # 2) 兜底：扫 runs/*/process/job_detail.json 取最新的（向后兼容老位置）
    runs_dir = out.runs_dir
    if os.path.isdir(runs_dir):
        try:
            run_dirs = sorted(
                (os.path.join(runs_dir, d) for d in os.listdir(runs_dir)),
                key=lambda p: os.path.getmtime(p),
                reverse=True,
            )
            for rd in run_dirs:
                jd = os.path.join(rd, "process", "job_detail.json")
                if os.path.exists(jd):
                    data = json.load(open(jd, encoding="utf-8"))
                    jid = data.get("encryptJobId") or data.get("job_id") or ""
                    if jid:
                        return jid
        except Exception:
            pass

    # 3) 老位置（顶层 process/）
    legacy = os.path.join(out.job_dir, "process", "job_detail.json")
    if os.path.exists(legacy):
        try:
            data = json.load(open(legacy, encoding="utf-8"))
            return data.get("encryptJobId") or ""
        except Exception:
            pass

    return ""
