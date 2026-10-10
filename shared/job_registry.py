# -*- coding: utf-8 -*-
"""Job metadata 注册表

设计原则（2026-07-29）：
- **不可变 ID = `encryptJobId`**：BOSS 自带、天然唯一、与候选人 geek_id 同源。
  所有文件系统路径（state/、runs/、reports/）都用此 ID 作目录名。
- **人类可读信息 = jobs.json metadata**：岗位名、公司、薪资等只放 jobs.json，
  报告/UI 从这里取。岗位重命名不影响文件系统。

调用模式：
- 旧调用：JobOutputManager(job_name="结构设计、研发工程师")
- 新调用（推荐）：JobOutputManager(encrypt_job_id="DemoJobId000000000000000000001")
                  或 JobOutputManager.from_job_name("结构设计、研发工程师")

向后兼容：
- 旧目录（<岗位中文名>/）仍可工作 —— job_name 会被当作目录名，jobs.json
  里自动登记一条 {name, encrypt_job_id=null}（如果暂不知道 encrypt_job_id）。
- 一次性迁移工具：`scripts/migrate_to_job_id.py`（TODO）。

文件名/路径里的"岗位中文名"暂保留不动（用户可见层），底层逻辑改用 ID。
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict

# jobs.json 路径：固定在 BOSS_HR_OUTPUT_DIR 根目录下
JOBS_REGISTRY_PATH = os.environ.get(
    'BOSS_HR_JOBS_REGISTRY',
    os.path.join(
        os.environ.get('BOSS_HR_OUTPUT_DIR') or os.path.expanduser('~/Desktop/boss-hr-output'),
        'jobs.json'
    ),
)


class JobRegistry:
    """岗位 metadata 注册表（持久化到 jobs.json）"""

    def __init__(self, path: str = None):
        self.path = path or JOBS_REGISTRY_PATH

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"version": 1, "jobs": {}}
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"version": 1, "jobs": {}}

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def register(self, encrypt_job_id: str, name: str = None,
                 company: str = None, **extra) -> None:
        """登记或更新一个岗位的 metadata。幂等。"""
        if not encrypt_job_id:
            raise ValueError("encrypt_job_id 必填")
        data = self._load()
        job = data["jobs"].setdefault(encrypt_job_id, {
            "encrypt_job_id": encrypt_job_id,
            "name": name,
            "company": company,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        # 增量更新字段（不覆盖已有值除非显式传）
        if name:
            job["name"] = name
        if company:
            job["company"] = company
        for k, v in extra.items():
            if v is not None:
                job[k] = v
        job["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._save(data)

    def get(self, encrypt_job_id: str) -> Optional[dict]:
        return self._load()["jobs"].get(encrypt_job_id)

    def by_name(self, name: str) -> Optional[dict]:
        """按岗位名反查（慢，但供一次性 / 迁移用）"""
        for jid, j in self._load()["jobs"].items():
            if j.get("name") == name:
                return j
        return None

    def all(self) -> Dict[str, dict]:
        return self._load()["jobs"]


# 模块级便捷函数
def resolve_job_dir(encrypt_job_id: str, name: str = None) -> str:
    """根据 encrypt_job_id 解析岗位目录绝对路径。

    优先从 jobs.json 查 job_id 对应 name（人类可读名字）；
    如果不在 jobs.json 且给了 name，自动登记一条。
    """
    reg = JobRegistry()
    job = reg.get(encrypt_job_id)
    if not job and name:
        reg.register(encrypt_job_id, name=name)
        job = reg.get(encrypt_job_id)
    if not job:
        # 没法登记（没给 name），退化用 job_id 作目录名
        from output_manager import OUTPUT_ROOT
        return os.path.join(OUTPUT_ROOT, encrypt_job_id)

    from output_manager import OUTPUT_ROOT
    return os.path.join(OUTPUT_ROOT, encrypt_job_id)