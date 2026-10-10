# -*- coding: utf-8 -*-
"""boss-hr confirm 命令测试（tests/cli/）

11 个用例：
  1. confirmed=false → true
  2. user_confirmed_at 正确写入
  3. run 不存在
  4. encrypt_job_id 不匹配
  5. 缺 run_id
  6. 缺 encrypt_job_id
  7. 不修改除当前 run.json 外的文件
  8. 不触发 recommend_list / recommend_download
  9. 不扫描最新 run
 10. 重复 confirm 行为与旧脚本一致
 11. 新旧实现状态变化等价

走 subprocess 调 python boss_hr/cli.py confirm ...
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent.parent
_CLI = _TOOLKIT_ROOT / "boss_hr" / "cli.py"
_SCRIPTS_CONFIRM = _TOOLKIT_ROOT / "shared"
_SHARED = _TOOLKIT_ROOT / "shared"


def _run_cli(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(_SHARED)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), *args],
        capture_output=True, env=env, cwd=str(_TOOLKIT_ROOT), timeout=30,
    )


def _run_old(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(_SHARED)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(_SCRIPTS_CONFIRM / "confirm_run.py"), *args],
        capture_output=True, env=env, cwd=str(_SCRIPTS_CONFIRM), timeout=30,
    )


def _file_hashes(root: Path) -> dict[str, str]:
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _make_run(root: Path, eid: str, rid: str, job_name: str,
              *, confirmed: bool = False, steps_done: list[str] | None = None) -> Path:
    run_dir = root / eid / "runs" / rid
    process_dir = run_dir / "process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid,
        "started_at": "2026-08-03 12:00:00",
        "confirmed": confirmed,
        "user_confirmed_at": "2026-08-03 13:00:00" if confirmed else None,
        "steps_done": steps_done or [],
        "last_step": (steps_done or [None])[-1],
        "finished": False, "finished_at": None,
    }, ensure_ascii=False), encoding="utf-8")
    (process_dir / "job_detail.json").write_text(json.dumps({
        "jobName": job_name, "encryptJobId": eid,
    }, ensure_ascii=False), encoding="utf-8")
    return run_dir


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """target run（confirmed=False）+ other run（诱饵 confirmed=True，finished=True）。"""
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid = "test_eid_confirm"
    job_name = "confirm_test_job"
    target = "2026-08-03_120000"
    other = "2026-08-02_120000"
    _make_run(tmp_path, eid, target, job_name, confirmed=False, steps_done=[])
    _make_run(tmp_path, eid, other, job_name,
              confirmed=True, steps_done=["jd", "download", "score", "report"])
    return tmp_path, eid, job_name, target, other


# ============================================================
# 1. confirmed=false → true
# ============================================================

def test_confirm_flips_to_true(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    env_extra = {"BOSS_HR_OUTPUT_DIR": str(tmp_path)}
    run_json = tmp_path / eid / "runs" / target / "run.json"
    before = json.loads(run_json.read_text(encoding="utf-8"))
    assert before["confirmed"] is False

    proc = _run_cli("confirm", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "confirm"
    assert payload["status"] == "confirmed"
    assert payload["run_id"] == target
    assert payload["next_action"] == "fetch"

    after = json.loads(run_json.read_text(encoding="utf-8"))
    assert after["confirmed"] is True


# ============================================================
# 2. user_confirmed_at 正确写入
# ============================================================

def test_confirm_writes_user_confirmed_at(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("confirm", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["data"]["confirmed"] is True
    assert payload["data"]["user_confirmed_at"] is not None
    # run.json 也必须有
    run_json = json.loads((tmp_path / eid / "runs" / target / "run.json").read_text(encoding="utf-8"))
    assert run_json["user_confirmed_at"] is not None


# ============================================================
# 3. run 不存在
# ============================================================

def test_confirm_run_not_found(workspace):
    tmp_path, eid, job_name, _target, _other = workspace
    proc = _run_cli("confirm", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", "9999-99-99_999999",
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 23
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "RUN_NOT_FOUND"


# ============================================================
# 4. encrypt_job_id 不匹配（run_id 存在但 encryptJobId 不对）
# ============================================================

def test_confirm_encrypt_job_id_mismatch(tmp_path, monkeypatch):
    """在 tmp 里建一个 run（encryptJobId=A），然后用 encrypt_job_id=B 去 confirm。"""
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    _make_run(tmp_path, "test_eid_real", "2026-08-03_120000", "mismatch_job")
    # 用错的 eid 去找 runs_dir 找不到 run → 走 RUN_NOT_FOUND（exit 23）
    # 这是预期的旧行为（confirm_run.py 也是这样）
    proc = _run_cli("confirm", "--job-name", "mismatch_job",
                    "--encrypt-job-id", "wrong_eid_xyz",
                    "--run-id", "2026-08-03_120000",
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 23
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "RUN_NOT_FOUND"


# ============================================================
# 5. 缺 run_id（argparse exit 2）
# ============================================================

def test_confirm_missing_run_id_argv(workspace):
    tmp_path, eid, job_name, _target, _other = workspace
    proc = _run_cli("confirm", "--job-name", job_name,
                    "--encrypt-job-id", eid,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    # argparse 默认 exit 2
    assert proc.returncode == 2


# ============================================================
# 6. 缺 encrypt_job_id（无 env）→ exit 1
# ============================================================

def test_confirm_missing_encrypt_job_id(workspace, monkeypatch):
    """缺 --encrypt-job-id（且 env BOSS_HR_ENCRYPT_JOB_ID 也没有）→ argparse rc=2。

    统一行为：缺公开 CLI 必填参数都 rc=2。
    """
    tmp_path, eid, job_name, target, _other = workspace
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(_SHARED)}
    env["BOSS_HR_OUTPUT_DIR"] = str(tmp_path)
    env.pop("BOSS_HR_ENCRYPT_JOB_ID", None)
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), "confirm",
         "--job-name", job_name, "--run-id", target],
        capture_output=True, env=env, cwd=str(_TOOLKIT_ROOT), timeout=30,
    )
    assert proc.returncode == 2
    stderr_text = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, bytes) else (proc.stderr or "")
    assert "--encrypt-job-id" in stderr_text


# ============================================================
# 7. 不修改除当前 run.json 外的文件
# ============================================================

def test_confirm_does_not_modify_other_files(workspace):
    tmp_path, eid, _job_name, _target, other = workspace
    job_dir = tmp_path / eid
    before = _file_hashes(job_dir)
    target = "2026-08-03_120000"  # workspace fixture 硬编码
    proc = _run_cli("confirm", "--job-name", "confirm_test_job",
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    after = _file_hashes(job_dir)

    new = set(after) - set(before)
    removed = set(before) - set(after)
    changed = [f for f in (set(before) & set(after)) if before[f] != after[f]]

    # 允许修改：当前 run 的 run.json（confirmed 字段）
    # rglob 相对路径在 Windows 用 \\，用 os.sep 兼容
    expected = f"runs{os.sep}{target}{os.sep}run.json"
    assert all(expected in f for f in changed), \
        f"只有当前 run.json 应被修改，但改了：{changed}"
    assert not new, f"confirm 不应新建任何文件，但新增：{new}"
    assert not removed, f"confirm 不应删除任何文件，但删除：{removed}"


# ============================================================
# 8. 不触发 recommend_list / recommend_download
# ============================================================

def test_confirm_does_not_trigger_fetch(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("confirm", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0

    # confirm 不应新建 recommend_geek_ids.json（Step 2 产物）
    target_dir = tmp_path / eid / "runs" / target
    assert not (target_dir / "process" / "recommend_geek_ids.json").exists(), \
        "confirm 触发 fetch 是禁止的"
    assert not (target_dir / "process" / "new_resumes.json").exists(), \
        "confirm 触发 download 是禁止的"
    # run.json.steps_done 仍为 []（confirm 不写 steps_done）
    run_json = json.loads((target_dir / "run.json").read_text(encoding="utf-8"))
    assert run_json["steps_done"] == []
    assert "download" not in run_json["steps_done"]


# ============================================================
# 9. 不扫描最新 run（与 status 的 latest-run 测试同形态）
# ============================================================

def test_confirm_does_not_pick_latest_run(workspace):
    tmp_path, eid, job_name, target, other = workspace
    # 写一个 legacy state/current_run.json 指 other（latest）
    legacy = tmp_path / eid / "state" / "current_run.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"current_run_id": other}), encoding="utf-8")

    proc = _run_cli("confirm", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["run_id"] == target
    assert payload["run_id"] != other  # 关键：没有自动选 latest


# ============================================================
# 10. 重复 confirm 行为与旧脚本一致
# ============================================================

def test_confirm_repeat_run_is_idempotent(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    env_extra = {"BOSS_HR_OUTPUT_DIR": str(tmp_path)}

    proc1 = _run_cli("confirm", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc1.returncode == 0
    p1 = json.loads(proc1.stdout)
    first_at = p1["data"]["user_confirmed_at"]

    proc2 = _run_cli("confirm", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc2.returncode == 0
    p2 = json.loads(proc2.stdout)
    # 重复 confirm 不应报错；confirmed 仍 true（RunOrchestrator.confirm_run 幂等）
    assert p2["data"]["confirmed"] is True
    # 注：RunOrchestrator.confirm_run 每次都会刷 user_confirmed_at 时间戳
    # （_now_str() 重新生成），这是旧 confirm_run.py 的行为；新 CLI 复用，
    # 所以也刷新。不校验时间戳稳定性。


# ============================================================
# 11. 新旧实现状态变化等价
# ============================================================

def test_confirm_new_old_state_equivalent(workspace):
    """同一份 run.json，新 CLI vs 旧 confirm_run.py，跑后 run.json 应等价。"""
    tmp_path, eid, job_name, target, _other = workspace
    env_extra = {"BOSS_HR_OUTPUT_DIR": str(tmp_path)}

    # 新 CLI 先跑
    proc_new = _run_cli("confirm", "--job-name", job_name,
                        "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc_new.returncode == 0
    new_run_json = json.loads(
        (tmp_path / eid / "runs" / target / "run.json").read_text(encoding="utf-8"))

    # 重置 run.json 到初始状态，再跑旧脚本
    init_state = {
        "run_id": target, "encrypt_job_id": eid,
        "started_at": "2026-08-03 12:00:00",
        "confirmed": False, "user_confirmed_at": None,
        "steps_done": [], "last_step": None,
        "finished": False, "finished_at": None,
    }
    (tmp_path / eid / "runs" / target / "run.json").write_text(
        json.dumps(init_state, ensure_ascii=False), encoding="utf-8")
    proc_old = _run_old("--job-name", job_name,
                        "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc_old.returncode == 0
    old_run_json = json.loads(
        (tmp_path / eid / "runs" / target / "run.json").read_text(encoding="utf-8"))

    # 关键字段等价
    assert new_run_json["confirmed"] == old_run_json["confirmed"] is True
    assert new_run_json["run_id"] == old_run_json["run_id"] == target
    assert new_run_json["encrypt_job_id"] == old_run_json["encrypt_job_id"] == eid
    assert new_run_json["steps_done"] == old_run_json["steps_done"] == []
    assert new_run_json["finished"] == old_run_json["finished"] is False
    # user_confirmed_at 格式都是 "%Y-%m-%d %H:%M:%S"；同年同秒应一致
    # （不能严格相等因为两秒跑）
    assert new_run_json["user_confirmed_at"] is not None
    assert old_run_json["user_confirmed_at"] is not None
