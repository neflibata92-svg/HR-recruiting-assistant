# -*- coding: utf-8 -*-
"""boss-hr status 命令测试（tests/cli/）

6 条核心约束：
  1. 只读，不修改任何状态文件
  2. 必须显式传 encrypt_job_id 和 run_id
  3. 不扫描最新 run
  4. 不读取 current_run.json
  5. 不从其他 run 补数据
  6. 不修改 run.json / process/ 任何文件
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ============================================================
# helper：定位 cli.py 入口
# ============================================================

_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent.parent
_CLI = _TOOLKIT_ROOT / "boss_hr" / "cli.py"


def _run_cli(*args: str, env_extra: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """subprocess 调 python boss_hr/cli.py <args>。

    必须走 subprocess（不 import cli.cmd_status）—— 否则 cli 内部的
    `sys.path.insert(0, .../shared)` 会污染测试自己的 import 表。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=cwd or _TOOLKIT_ROOT, timeout=15,
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """造一个干净的「一个 encrypt_job_id + 两个 run」工作区。

    返回 (job_name, encrypt_job_id, target_run_id, other_run_id, workspace_root)。
    通过 BOSS_HR_OUTPUT_DIR 把 output_manager 输出根指向 tmp_path。
    同时预先建好 runs/<target_run_id>/process/{job_detail.json, run.json}
    让 status 命令能跑通。
    """
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))

    job_name = "结构设计、研发工程师"
    encrypt_job_id = "test_encrypt_job_id_xyz"
    target_run_id = "2026-01-01_120000"
    other_run_id = "2026-01-02_120000"

    job_dir = tmp_path / encrypt_job_id
    for rid in (target_run_id, other_run_id):
        run_dir = job_dir / "runs" / rid / "process"
        run_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "runs" / rid / "run.json").write_text(json.dumps({
            "run_id": rid,
            "encrypt_job_id": encrypt_job_id,
            "started_at": "2026-01-01 12:00:00",
            "confirmed": True,
            "user_confirmed_at": "2026-01-01 12:01:00",
            "steps_done": ["jd", "download"],
            "last_step": "download",
            "last_step_at": "2026-01-01 12:30:00",
            "finished": False,
            "finished_at": None,
        }, ensure_ascii=False), encoding="utf-8")
        (run_dir / "job_detail.json").write_text(json.dumps({
            "jobName": job_name,
            "encryptJobId": encrypt_job_id,
        }, ensure_ascii=False), encoding="utf-8")

    return job_name, encrypt_job_id, target_run_id, other_run_id, tmp_path


def _file_hashes(root: Path) -> dict[str, str]:
    """列 root 下所有文件的相对路径 + sha256。"""
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ============================================================
# 1. 只读约束：不修改任何状态文件
# ============================================================

def test_status_does_not_modify_any_file(workspace):
    """跑一次 status，对比前后所有文件 sha256，验证零修改。"""
    job_name, eid, rid, _other, ws = workspace
    job_dir = ws / eid

    before = _file_hashes(job_dir)
    proc = _run_cli(
        "status",
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        "--run-id", rid,
        env_extra={"BOSS_HR_OUTPUT_DIR": str(ws)},
    )
    after = _file_hashes(job_dir)

    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert before == after, "status 修改了工作区文件！只读约束被破坏"


# ============================================================
# 2. 必传 encrypt_job_id + run_id
# ============================================================

def test_status_requires_encrypt_job_id(workspace):
    """缺 --encrypt-job-id 且无环境变量 → argparse 报 rc=2（缺必填参数）。

    统一行为：缺任一公开 CLI 必填参数都 rc=2，由 commands/_argparse_helpers
    统一处理。
    """
    job_name, _eid, rid, _other, ws = workspace
    proc = _run_cli(
        "status",
        "--job-name", job_name,
        "--run-id", rid,
        env_extra={"BOSS_HR_OUTPUT_DIR": str(ws)},
    )
    assert proc.returncode == 2
    stderr_text = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, bytes) else (proc.stderr or "")
    assert "--encrypt-job-id" in stderr_text


def test_status_requires_run_id(workspace):
    """缺 --run-id → argparse exit 2。"""
    job_name, eid, _rid, _other, ws = workspace
    proc = _run_cli(
        "status",
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        env_extra={"BOSS_HR_OUTPUT_DIR": str(ws)},
    )
    # argparse 默认对 --required 参数缺失时 exit 2
    assert proc.returncode == 2


# ============================================================
# 3. 不扫描最新 run
# ============================================================

def test_status_targets_explicit_run_not_latest(workspace):
    """两个 run 存在（target 早于 other），status 指定 target 时
    必须返回 target 的状态，而不是 other（latest）。"""
    job_name, eid, rid, other, ws = workspace
    proc = _run_cli(
        "status",
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        "--run-id", rid,  # 显式早的那个
        env_extra={"BOSS_HR_OUTPUT_DIR": str(ws)},
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["run_id"] == rid
    assert payload["run_id"] != other  # 不是 latest（other 才是字典序最新）


# ============================================================
# 4. 不读取 current_run.json
# ============================================================

def test_status_ignores_current_run_json(workspace):
    """工作区里有 legacy state/current_run.json 指其他 run → status 仍按 --run-id 工作。"""
    job_name, eid, rid, other, ws = workspace
    # legacy 文件（2026-07-30 之前的设计）：指到 other 这个 run
    legacy = ws / eid / "state" / "current_run.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"current_run_id": other}), encoding="utf-8")

    proc = _run_cli(
        "status",
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        "--run-id", rid,
        env_extra={"BOSS_HR_OUTPUT_DIR": str(ws)},
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    # 即使 current_run.json 指到 other，status 必须按 --run-id 返回
    assert payload["run_id"] == rid
    assert payload["run_id"] != other


# ============================================================
# 5. 不从其他 run 补数据
# ============================================================

def test_status_does_not_borrow_from_other_run(workspace):
    """target run_dir 完全不存在，但 other run 有完整数据；
    status 必须按 --run-id 返回 FileNotFoundError（exit 23），不从 other 补。

    注：bind_existing_run 只校验 runs/<run_id>/ 目录是否存在，不校验 process/ 内容。
    所以这个测试必须把 target run 的整个目录删掉才能触发 FileNotFoundError。
    """
    job_name, eid, rid, other, ws = workspace
    target_dir = ws / eid / "runs" / rid
    if target_dir.exists():
        import shutil
        shutil.rmtree(target_dir)

    proc = _run_cli(
        "status",
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        "--run-id", rid,
        env_extra={"BOSS_HR_OUTPUT_DIR": str(ws)},
    )
    # target run_dir 不存在 → bind_existing_run 抛 FileNotFoundError → exit 23
    assert proc.returncode == 23, f"unexpected exit={proc.returncode} stdout={proc.stdout!r}"
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert "不存在" in payload["message"]
    assert payload["run_id"] == rid  # 仍然回显请求的 run_id，不是 other
    assert payload["run_id"] != other  # 关键：没有从 other run 借数据返回 200


# ============================================================
# 6. 核心字段正确
# ============================================================

def test_status_returns_core_fields(workspace):
    job_name, eid, rid, _other, ws = workspace
    proc = _run_cli(
        "status",
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        "--run-id", rid,
        env_extra={"BOSS_HR_OUTPUT_DIR": str(ws)},
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    # 核心字段
    assert payload["status"] == "ok"
    assert payload["command"] == "status"
    assert payload["run_id"] == rid
    assert payload["encrypt_job_id"] == eid
    assert payload["job_name"] == job_name
    assert payload["confirmed"] is True
    assert payload["finished"] is False
    assert payload["steps_done"] == ["jd", "download"]
    assert payload["workflow_state"] == "ready_to_score"
    # paths 必须以 target run 结尾（用 Path 比较，跨平台安全）
    assert Path(payload["paths"]["run_dir"]).name == rid
    assert Path(payload["paths"]["process_dir"]).name == "process"
    assert Path(payload["paths"]["process_dir"]).parent.name == rid
