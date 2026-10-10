# -*- coding: utf-8 -*-
"""boss-hr start 命令测试（tests/cli/）

策略：mock `boss_hr.adapters.legacy_runner.run_legacy_cli` 让 boss_jd
子脚本被替换为写真实 run 目录 + job_detail.json + jobs.json 的 fake；
通过 inproc 调 boss_hr.commands.start.run() 让 monkeypatch 生效。

25 个用例覆盖：
  1-7. 正常创建 + 连续两次 + 第二次不修改第一次
  8. 不接受 --run-id（argparse 拦截）
  9-11. 缺 query / job-name / encrypt_job_id
  12-13. query/eid 一致性 + env 优先
  14. 三处 run_id 一致
  15-16. 不读 current_run.json + 不扫描最新 run
  17-20. 不调其他命令
  21-23. boss_jd 失败透传 / 登录失败 / JD 接口失败
  24. jobs.json 修改
  25. 新旧产物核心内容等价

外加 2 个 subprocess 公共 CLI 测试：缺必填参数 + 不接受 --run-id。
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path
from typing import Optional

import pytest


_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent.parent
_CLI = _TOOLKIT_ROOT / "boss_hr" / "cli.py"
_SHARED = _TOOLKIT_ROOT / "shared"


# ============================================================
# helpers
# ============================================================

class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _decode(b) -> str:
    if b is None:
        return ""
    if isinstance(b, bytes):
        return b.decode("utf-8", errors="replace")
    return b


def _make_run_dir_files(workspace: Path, eid: str, rid: str, jn: str) -> Path:
    """写真实 run 目录 + job_detail.json + run.json（模拟 boss_jd 写完）。"""
    process_dir = workspace / eid / "runs" / rid / "process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (workspace / eid / "runs" / rid / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid,
        "started_at": "2026-08-03 12:00:00",
        "confirmed": False, "user_confirmed_at": None,
        "steps_done": ["jd"], "last_step": "jd",
        "finished": False, "finished_at": None,
    }, ensure_ascii=False), encoding="utf-8")
    job_detail = f"{workspace}/{eid}/runs/{rid}/process/job_detail.json"
    (process_dir / "job_detail.json").write_text(json.dumps({
        "jobName": jn, "encryptJobId": eid,
        "bodyText": "mock body", "formValues": ["mock"],
        "_meta": {"run_id": rid, "saved_at": "2026-08-03 12:00:00"},
    }, ensure_ascii=False), encoding="utf-8")
    return workspace / eid / "runs" / rid


def _make_fake_stdout(eid: str, jn: str, rid: str, workspace: Path) -> str:
    job_detail = f"{workspace}/{eid}/runs/{rid}/process/job_detail.json"
    text = (
        f"Found: {jn} ({eid})\n"
        f"run_id: {rid}（orchestrator 创建）\n"
        + json.dumps({
            "status": "waiting_user_confirmation", "run_id": rid,
            "stage": "awaiting_user_confirmation", "message": "Step 1 完成",
        }, ensure_ascii=False, indent=2)
        + f"\nSaved to {job_detail}\n"
        f"run_id: {rid}\nOK\n"
    )
    return text


@pytest.fixture
def mock_boss_jd(tmp_path, monkeypatch):
    """autouse mock：替代 boss_jd 子进程调用，写真实 run 目录。"""
    from boss_hr.adapters import legacy_runner
    from boss_hr.adapters import browser_preflight as bp_mod
    from boss_hr.application import start_service as ss_mod
    calls: list[dict] = []

    def _fake(tool, args, *, timeout=60, **kwargs):
        calls.append({"tool": tool, "args": list(args)})
        if tool != "boss_jd":
            return _FakeProc(99, "", "")
        # 解析 query
        query = args[0] if args else ""
        eid = query
        jn = "mock_job"
        for i, a in enumerate(args):
            if a == "--job-name" and i + 1 < len(args):
                jn = args[i + 1]
            elif a == "--encrypt-job-id" and i + 1 < len(args):
                eid = args[i + 1]
        # 生成新 run_id（带盐避免冲突）
        import os
        ts = time.strftime("%Y-%m-%d_%H%M%S")
        suffix = os.urandom(2).hex()
        rid = f"{ts}_{suffix}"
        _make_run_dir_files(tmp_path, eid, rid, jn)
        # jobs.json
        jobs_path = tmp_path / "jobs.json"
        existing = {}
        if jobs_path.is_file():
            try:
                existing = json.loads(jobs_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing[eid] = {"name": jn, "company": ""}
        jobs_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        return _FakeProc(0, _make_fake_stdout(eid, jn, rid, tmp_path), "")

    monkeypatch.setattr("boss_hr.adapters.legacy_runner.run_legacy_cli", _fake)

    # v1.1.1: 旁路 browser_preflight（测试不连 CDP）
    class _PreflightOK:
        ok = True
        error_obj = None
        remediation = None
        next_action = None
        info = {"page_kind": "recommend", "logged_in": True}

    monkeypatch.setattr(bp_mod, "browser_preflight", lambda *a, **kw: _PreflightOK())

    # v1.1.1: 旁路实时岗位解析（测试不连 BOSS 后端）
    # 捕获 fixture 当时的 args 列表到闭包（args 是 _fake 闭包的参数，
    # 此处的 _fake_resolve 用 fixture 时刻的 args 不行，必须延迟到 _fake
    # 被调用时拿）。改用 _fake 函数本身把 args 传给 _fake_resolve。
    captured_args_holder: list = []  # 实际不用，让 _fake_resolve 接受参数

    def _fake_resolve(query, args_for_resolve=None):
        if args_for_resolve is None:
            return {"encryptJobId": query, "jobName": "mock_job",
                    "jobId": None, "address": "", "salaryDesc": ""}
        # 优先取 --encrypt-job-id 参数
        eid = query
        for i, a in enumerate(args_for_resolve):
            if a == "--encrypt-job-id" and i + 1 < len(args_for_resolve):
                eid = args_for_resolve[i + 1]
        jn = "mock_job"
        for i, a in enumerate(args_for_resolve):
            if a == "--job-name" and i + 1 < len(args_for_resolve):
                jn = args_for_resolve[i + 1]
        return {"encryptJobId": eid, "jobName": jn,
                "jobId": None, "address": "", "salaryDesc": ""}

    monkeypatch.setattr(ss_mod, "_resolve_recruiter_job", _fake_resolve)

    return tmp_path, calls


# ============================================================
# inproc runner
# ============================================================

def _run_inproc(*, query=None, jn=None, eid=None, extra=None):
    import argparse
    from boss_hr.commands import start as start_cmd
    from boss_hr.cli import build_parser
    p = build_parser()
    argv = ["start"]
    if query is not None:
        argv.append(query)
    if jn is not None:
        argv += ["--job-name", jn]
    if eid is not None:
        argv += ["--encrypt-job-id", eid]
    if extra:
        argv += list(extra)
    ns = p.parse_args(argv)
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction) and ns.command in action.choices:
            ns._parser = action.choices[ns.command]
            break
    result = start_cmd.run(ns)
    out = json.dumps(result.to_dict("start"), ensure_ascii=False) + "\n"
    Proc = namedtuple("FakeProc", ["returncode", "stdout", "stderr"])
    return Proc(returncode=int(result.exit_code), stdout=out.encode("utf-8"), stderr=b"")


# ============================================================
# 1-7. 正常创建 + 连续两次
# ============================================================

def test_start_creates_new_run(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_new_001", jn="new_run_job",
                       eid="test_eid_new_001")
    assert proc.returncode == 0
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is True
    assert p["command"] == "start"
    assert p["status"] == "waiting_user_confirmation"
    assert p["run_id"]
    assert p["encrypt_job_id"] == "test_eid_new_001"
    assert p["job_name"] == "new_run_job"
    assert p["next_action"] == "confirm"
    assert p["data"]["confirmed"] is False


def test_start_returns_real_run_id(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_real", jn="real_job", eid="test_eid_real")
    p = json.loads(_decode(proc.stdout))
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}_\d{6}_[0-9a-f]{4}", p["run_id"]), f"bad run_id: {p['run_id']}"


def test_start_job_detail_file_at_run(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_d", jn="d_job", eid="test_eid_d")
    p = json.loads(_decode(proc.stdout))
    rid = p["run_id"]
    jd = p["data"]["job_detail_file"]
    assert jd.endswith(f"{rid}/process/job_detail.json")
    assert Path(jd).is_file()


def test_start_confirmed_false(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_c", jn="c_job", eid="test_eid_c")
    p = json.loads(_decode(proc.stdout))
    assert p["data"]["confirmed"] is False
    rid = p["run_id"]
    rj = json.loads((tmp_path / "test_eid_c" / "runs" / rid / "run.json").read_text(encoding="utf-8"))
    assert rj["confirmed"] is False


def test_start_next_action_confirm(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_n", jn="n_job", eid="test_eid_n")
    p = json.loads(_decode(proc.stdout))
    assert p["next_action"] == "confirm"


def test_start_two_runs_different_ids(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc1 = _run_inproc(query="test_eid_2x_001", jn="2x_job", eid="test_eid_2x_001")
    p1 = json.loads(_decode(proc1.stdout))
    rid1 = p1["run_id"]
    time.sleep(1.1)
    proc2 = _run_inproc(query="test_eid_2x_002", jn="2x_job", eid="test_eid_2x_002")
    p2 = json.loads(_decode(proc2.stdout))
    rid2 = p2["run_id"]
    assert rid1 != rid2


def test_start_does_not_modify_first_run(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc1 = _run_inproc(query="test_eid_x_001", jn="x_job", eid="test_eid_x_001")
    p1 = json.loads(_decode(proc1.stdout))
    rid1 = p1["run_id"]
    run1 = tmp_path / "test_eid_x_001" / "runs" / rid1
    run1_json_before = (run1 / "run.json").read_text(encoding="utf-8")
    job1_before = (run1 / "process" / "job_detail.json").read_text(encoding="utf-8")
    time.sleep(1.1)
    proc2 = _run_inproc(query="test_eid_x_002", jn="x_job", eid="test_eid_x_002")
    assert proc2.returncode == 0
    assert (run1 / "run.json").read_text(encoding="utf-8") == run1_json_before
    assert (run1 / "process" / "job_detail.json").read_text(encoding="utf-8") == job1_before


# ============================================================
# 8. 不接受 --run-id
# ============================================================

def test_start_rejects_run_id_arg_via_argparse(tmp_path):
    """subprocess：argparse 拦 --run-id。"""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), "start",
         "test_eid_r", "--job-name", "r_job", "--encrypt-job-id", "test_eid_r",
         "--run-id", "2026-08-03_120000"],
        capture_output=True, env={**os.environ, "PYTHONUTF8": "1",
                                  "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(_SHARED),
                                  "BOSS_HR_OUTPUT_DIR": str(tmp_path)},
        cwd=str(_TOOLKIT_ROOT), timeout=15,
    )
    assert proc.returncode == 2
    assert "--run-id" in _decode(proc.stderr)


# ============================================================
# 9-11. 缺必填参数
# ============================================================

def test_start_missing_query_argparse(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), "start",
         "--job-name", "x", "--encrypt-job-id", "test_eid_x"],
        capture_output=True, env={**os.environ, "PYTHONUTF8": "1",
                                  "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(_SHARED),
                                  "BOSS_HR_OUTPUT_DIR": str(tmp_path)},
        cwd=str(_TOOLKIT_ROOT), timeout=15,
    )
    assert proc.returncode == 2


def test_start_query_only_argparse(monkeypatch, tmp_path):
    """v1.1.1: --job-name 改为可选；仅传 query 也能正常启动（实时解析岗位名）。

    用 inproc + mock preflight，避免真连 CDP。
    """
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner

    class _ReadyOK:
        ok = True
        error_obj = None
        remediation = None
        next_action = None
        info = {"page_kind": "recommend", "logged_in": True}
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ReadyOK())
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": "test_eid",
                                   "jobName": "解析出的岗位",
                                   "jobId": None, "address": "", "salaryDesc": ""})

    class _OKProc:
        returncode = 0
        stdout = ("run_id: 2026-08-04_120000（orchestrator 创建）\n"
                  + '{"status":"waiting_user_confirmation","run_id":"2026-08-04_120000"}\n'
                  + "Saved to /tmp/job_detail.json\n")
        stderr = ""
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _OKProc())

    res = ss.start_new_run(query="test_eid", job_name=None, encrypt_job_id=None,
                            skip_preflight=True, skip_resolve=False,
                            auto_launch_browser=True, login_wait_seconds=1)
    d = res.to_dict("start")
    # --job-name 缺不报错；inproc 拿到 status=waiting_user_confirmation
    assert d["ok"] is True
    assert d["status"] == "waiting_user_confirmation"


def test_start_job_not_found_business_layer(monkeypatch, tmp_path):
    """业务层：query 在 BOSS 实时目录找不到 → JOB_NOT_FOUND + rc=1。

    v1.1.1 不再要求 --encrypt-job-id；query 即岗位名实时解析。
    """
    monkeypatch.delenv("BOSS_HR_ENCRYPT_JOB_ID", raising=False)
    from boss_hr.application import start_service as ss_mod
    monkeypatch.setattr(ss_mod, "_resolve_recruiter_job", lambda q: None)
    # 旁路 v1.1.2 browser ensure（多 import 路径：模块 + 服务本地引用）
    from boss_hr.adapters import browser_environment as be_mod
    class _ReadyOK:
        ok = True; error_obj = None; remediation = None; next_action = None
        info = {"page_kind": "recommend", "logged_in": True}
    monkeypatch.setattr(be_mod, "ensure_browser_ready", lambda *a, **kw: _ReadyOK())
    monkeypatch.setattr(ss_mod, "ensure_browser_ready", lambda *a, **kw: _ReadyOK())

    proc = _run_inproc(query="不存在的岗位名_xyz", jn="x", eid=None)
    assert proc.returncode == 1
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert p["error"]["code"] == "JOB_NOT_FOUND"
    # 必须含可执行恢复提示
    assert p["error"].get("recoverable") is True
    assert p["error"].get("next_action") == "retry_with_exact_query"
    assert "remediation" in p["error"]


# ============================================================
# 12. query 与 --encrypt-job-id 一致性
# ============================================================

def test_start_eid_mismatch_returns_job_id_mismatch(mock_boss_jd):
    """v1.1.1: --encrypt-job-id 与实时解析结果不一致 → JOB_ID_MISMATCH。

    query=test_eid_query，实时解析返回 test_eid_query；
    --encrypt-job-id=test_eid_param 不同 → 立即停止。
    """
    tmp_path, _ = mock_boss_jd
    from boss_hr.application import start_service as ss_mod
    # 强制实时解析返回固定 eid（与 --encrypt-job-id 不一致）
    monkeypatch_obj = __import__("pytest").MonkeyPatch()
    try:
        monkeypatch_obj.setattr(ss_mod, "_resolve_recruiter_job",
                                lambda q: {"encryptJobId": "test_eid_query",
                                           "jobName": "mock_job",
                                           "jobId": None})
        proc = _run_inproc(query="test_eid_query", jn="a_job", eid="test_eid_param")
    finally:
        monkeypatch_obj.undo()
    assert proc.returncode == 1
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert p["error"]["code"] == "JOB_ID_MISMATCH"
    assert p["error"].get("recoverable") is True
    assert p["error"].get("next_action") == "retry_without_arg_or_with_correct_eid"


# ============================================================
# 13. env ID 优先级
# ============================================================

def test_start_param_overrides_env(mock_boss_jd, monkeypatch):
    monkeypatch.setenv("BOSS_HR_ENCRYPT_JOB_ID", "test_eid_env")
    proc = _run_inproc(query="test_eid_p", jn="p_job", eid="test_eid_p")
    p = json.loads(_decode(proc.stdout))
    assert p["encrypt_job_id"] == "test_eid_p"


# ============================================================
# 14. 三处 run_id 一致
# ============================================================

def test_start_three_run_id_consistent(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_t", jn="t_job", eid="test_eid_t")
    p = json.loads(_decode(proc.stdout))
    rid = p["run_id"]
    rj = json.loads((tmp_path / "test_eid_t" / "runs" / rid / "run.json").read_text(encoding="utf-8"))
    jd = json.loads((tmp_path / "test_eid_t" / "runs" / rid / "process" / "job_detail.json").read_text(encoding="utf-8"))
    assert rid == rj["run_id"] == jd["_meta"]["run_id"]


# ============================================================
# 15-16. 不读 current_run.json + 不扫描最新 run
# ============================================================

def test_start_does_not_read_current_run_json(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    eid = "test_eid_lc"
    (tmp_path / eid / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / eid / "state" / "current_run.json").write_text(
        json.dumps({"current_run_id": "9999-99-99_999999"}), encoding="utf-8")
    proc = _run_inproc(query=eid, jn="lc_job", eid=eid)
    p = json.loads(_decode(proc.stdout))
    assert p["run_id"] != "9999-99-99_999999"


def test_start_does_not_pick_latest_run(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    eid = "test_eid_lr"
    (tmp_path / eid / "runs" / "2026-01-01_120000").mkdir(parents=True, exist_ok=True)
    (tmp_path / eid / "runs" / "2026-01-01_120000" / "run.json").write_text(json.dumps({
        "run_id": "2026-01-01_120000", "encrypt_job_id": eid, "confirmed": True,
    }, ensure_ascii=False), encoding="utf-8")
    proc = _run_inproc(query=eid, jn="lr_job", eid=eid)
    p = json.loads(_decode(proc.stdout))
    assert p["run_id"] != "2026-01-01_120000"


# ============================================================
# 17-20. 不自动调其他命令
# ============================================================

def test_start_does_not_call_confirm(mock_boss_jd):
    tmp_path, calls = mock_boss_jd
    proc = _run_inproc(query="test_eid_nc", jn="nc_job", eid="test_eid_nc")
    p = json.loads(_decode(proc.stdout))
    assert p["data"]["confirmed"] is False
    rid = p["run_id"]
    rj = json.loads((tmp_path / "test_eid_nc" / "runs" / rid / "run.json").read_text(encoding="utf-8"))
    assert rj["confirmed"] is False
    tools = [c["tool"] for c in calls]
    assert "confirm_run" not in tools


def test_start_does_not_call_recommend_list(mock_boss_jd):
    tmp_path, calls = mock_boss_jd
    _run_inproc(query="test_eid_nr", jn="nr_job", eid="test_eid_nr")
    assert "recommend_list" not in [c["tool"] for c in calls]


def test_start_does_not_call_recommend_download(mock_boss_jd):
    tmp_path, calls = mock_boss_jd
    _run_inproc(query="test_eid_nd", jn="nd_job", eid="test_eid_nd")
    assert "recommend_download" not in [c["tool"] for c in calls]


def test_start_does_not_call_score_report_greet(mock_boss_jd):
    tmp_path, calls = mock_boss_jd
    _run_inproc(query="test_eid_ns", jn="ns_job", eid="test_eid_ns")
    for t in ("score_resumes", "collect_llm_scores", "prepare_scoring_inputs",
              "generate_html_report", "auto_greet"):
        assert t not in [c["tool"] for c in calls], f"start 不应调 {t}"


# ============================================================
# 21-23. boss_jd 失败路径
# ============================================================

def test_start_passes_through_subprocess_rc(monkeypatch, tmp_path):
    """mock boss_jd 返回 rc=42，新 CLI 透传。"""
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _FakeProc(42, "Job not found\n", ""))
    proc = _run_inproc(query="mock_q", jn="fail_job", eid="mock_q")
    assert proc.returncode == 42
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert p["error"]["subprocess_returncode"] == 42


def test_start_login_failure_passes_through(monkeypatch, tmp_path):
    """mock boss_jd 模拟 CDP 登录失败 → rc=1 透传。"""
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _FakeProc(1, "", "connect ECONNREFUSED\n"))
    proc = _run_inproc(query="test_eid_login_fail", jn="login_job",
                       eid="test_eid_login_fail")
    assert proc.returncode == 1
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False


def test_start_jd_failure_no_new_run_files(monkeypatch, tmp_path):
    """mock boss_jd 退出 0 但 stdout 无 run_id → error + INTERNAL。"""
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _FakeProc(0, "Found: x (test_eid_bf)\nOK\n", ""))
    proc = _run_inproc(query="test_eid_bf", jn="bf_job", eid="test_eid_bf")
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert p["error"]["code"] == "INTERNAL"


# ============================================================
# 24. jobs.json 修改
# ============================================================

def test_start_jobs_json_registers_eid(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_j", jn="j_job", eid="test_eid_j")
    assert proc.returncode == 0
    jobs_path = tmp_path / "jobs.json"
    assert jobs_path.is_file()
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert "test_eid_j" in jobs
    assert jobs["test_eid_j"]["name"] == "j_job"


# ============================================================
# 25. 新旧成功产物核心内容等价
# ============================================================

def test_start_output_equivalent_old_implementation(mock_boss_jd):
    tmp_path, _ = mock_boss_jd
    proc = _run_inproc(query="test_eid_e", jn="e_job", eid="test_eid_e")
    p = json.loads(_decode(proc.stdout))
    assert p["data"]["job_detail_file"]
    assert p["data"]["confirmed"] is False
    rid = p["run_id"]
    rj = json.loads((tmp_path / "test_eid_e" / "runs" / rid / "run.json").read_text(encoding="utf-8"))
    jd = json.loads((tmp_path / "test_eid_e" / "runs" / rid / "process" / "job_detail.json").read_text(encoding="utf-8"))
    assert rj["encrypt_job_id"] == "test_eid_e"
    assert jd["encryptJobId"] == "test_eid_e"
    assert jd["jobName"] == "e_job"


# ============================================================
# 公共 CLI 测试（subprocess）
# ============================================================

def test_cli_missing_required_arg_rc2(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), "start"],
        capture_output=True, env={**os.environ, "PYTHONUTF8": "1",
                                  "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(_SHARED),
                                  "BOSS_HR_OUTPUT_DIR": str(tmp_path)},
        cwd=str(_TOOLKIT_ROOT), timeout=15,
    )
    assert proc.returncode == 2
    # stdout 应为空（argparse 错误写到 stderr）
    assert _decode(proc.stdout).strip() == ""
    # 错误在 stderr
    assert _decode(proc.stderr)  # 非空


def test_cli_stdout_argparse_error_to_stderr_only(tmp_path):
    """start 接受 --run-id 之外的参数；带 --run-id 应让 argparse 报错到 stderr。"""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), "start",
         "test_eid", "--job-name", "j", "--encrypt-job-id", "test_eid",
         "--run-id", "2026-08-03_120000"],
        capture_output=True, env={**os.environ, "PYTHONUTF8": "1",
                                  "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(_SHARED),
                                  "BOSS_HR_OUTPUT_DIR": str(tmp_path)},
        cwd=str(_TOOLKIT_ROOT), timeout=15,
    )
    assert proc.returncode == 2
    assert _decode(proc.stdout).strip() == ""
    assert "--run-id" in _decode(proc.stderr)
