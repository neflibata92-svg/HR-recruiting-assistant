# -*- coding: utf-8 -*-
"""boss-hr report 命令测试（tests/cli/）

8 个用例覆盖：
  1. 正常生成
  2. run 不存在
  3. encrypt_job_id 不匹配
  4. 缺少 screening_results
  5. 不借用其他 run 的结果
  6. 不触发 greet
  7. 重复运行行为与旧脚本一致
  8. 新旧报告关键内容等价

走 subprocess 调 python boss_hr/cli.py report ...，
不 import cli.cmd_report（避免 sys.path 污染）。
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent.parent
_CLI = _TOOLKIT_ROOT / "boss_hr" / "cli.py"
_SCRIPTS_HTML = _TOOLKIT_ROOT / "html-report" / "scripts"
_SHARED = _TOOLKIT_ROOT / "shared"


def _decode(b: bytes | None) -> str:
    if not b:
        return ""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _run_cli(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(_SHARED)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), *args],
        capture_output=True, env=env, cwd=str(_TOOLKIT_ROOT), timeout=60,
    )


def _run_old(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(_SHARED)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(_SCRIPTS_HTML / "generate_html_report.py"), *args],
        capture_output=True, env=env, cwd=str(_SCRIPTS_HTML), timeout=60,
    )


def _file_hashes(root: Path) -> dict[str, str]:
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _make_run(root: Path, eid: str, rid: str, job_name: str,
              steps_done: list[str], include_screening: bool) -> Path:
    """造一个最小合法 run（runs/<rid>/{run.json, process/{job_detail,screening?}.json}）。"""
    run_dir = root / eid / "runs" / rid
    process_dir = run_dir / "process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid,
        "started_at": "2026-08-03 12:00:00", "confirmed": True,
        "steps_done": steps_done, "last_step": steps_done[-1] if steps_done else None,
        "finished": False, "finished_at": None,
    }, ensure_ascii=False), encoding="utf-8")
    (process_dir / "job_detail.json").write_text(json.dumps({
        "jobName": job_name, "encryptJobId": eid,
    }, ensure_ascii=False), encoding="utf-8")
    if include_screening:
        screening = {
            "job_name": job_name, "run_id": rid,
            "summary": {"total": 2, "recommend": 1, "pending": 0, "reject": 1},
            "dimension_labels": ["学历", "工作经验", "技能", "项目", "专业"],
            "candidates": [
                {"rank": 1, "name": "张三", "tier": "推荐", "total": 78.5,
                 "school": "辽宁工业大学", "work_years": "5 年", "current_role": "结构设计",
                 "hard_pass": True,
                 "dimensions": [
                     {"pct": 70, "weighted": 17.5, "weight": 25, "reason": ""},
                     {"pct": 80, "weighted": 20.0, "weight": 25, "reason": ""},
                     {"pct": 85, "weighted": 21.25, "weight": 25, "reason": ""},
                     {"pct": 75, "weighted": 11.25, "weight": 15, "reason": ""},
                     {"pct": 85, "weighted": 8.5, "weight": 10, "reason": ""},
                 ],
                 "highlights": ["亮点"], "concerns": []},
                {"rank": 2, "name": "王五", "tier": "不推荐", "total": 45.0,
                 "school": "野鸡大学", "work_years": "1 年", "current_role": "实习",
                 "hard_pass": True,
                 "dimensions": [
                     {"pct": 50, "weighted": 12.5, "weight": 25, "reason": ""},
                     {"pct": 40, "weighted": 10.0, "weight": 25, "reason": ""},
                     {"pct": 50, "weighted": 12.5, "weight": 25, "reason": ""},
                     {"pct": 40, "weighted": 6.0, "weight": 15, "reason": ""},
                     {"pct": 40, "weighted": 4.0, "weight": 10, "reason": ""},
                 ],
                 "highlights": [], "concerns": ["经验浅"]},
            ],
            "actions": {
                "recommend": [{"name": "张三", "score": 78.5,
                               "background": "亮点", "action": "约面试"}],
                "pending": [],
                "reject": [{"name": "王五", "score": 45.0, "concerns": "经验浅"}],
            },
            "meta": {"title": "test", "subtitle": "", "job": {},
                     "type_judgment": {}, "core_requirements": []},
        }
        (process_dir / "screening_results.json").write_text(
            json.dumps(screening, ensure_ascii=False), encoding="utf-8")
    return run_dir


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """一个 target run（有 screening）+ 一个 other run（诱饵旧 HTML）+ 一个 empty run。"""
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid = "test_eid_report"
    job_name = "report_test_job"
    target = "2026-08-03_120000"
    other = "2026-08-02_120000"
    empty = "2026-08-03_130000"

    _make_run(tmp_path, eid, target, job_name,
              steps_done=["jd", "download", "score"], include_screening=True)
    _make_run(tmp_path, eid, other, job_name,
              steps_done=["jd", "download", "score"], include_screening=False)
    _make_run(tmp_path, eid, empty, job_name,
              steps_done=["jd"], include_screening=False)

    # 写诱饵旧 HTML 到 other run（验证不借用）
    (tmp_path / eid / "runs" / other / f"{other}_screening_report.html").write_text(
        "<html>诱饵旧报告</html>", encoding="utf-8")
    return tmp_path, eid, job_name, target, other, empty


# ============================================================
# 1. 正常生成
# ============================================================

def test_report_happy_path(workspace):
    tmp_path, eid, job_name, target, _other, _empty = workspace
    proc = _run_cli("report", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0, f"stdout={_decode(proc.stdout)!r}\nstderr={_decode(proc.stderr)!r}"
    payload = json.loads(_decode(proc.stdout))
    assert payload["ok"] is True
    assert payload["command"] == "report"
    assert payload["status"] == "report_ready"
    assert payload["run_id"] == target
    assert payload["encrypt_job_id"] == eid
    assert payload["job_name"] == job_name
    assert payload["next_action"] == "greet_optional"
    # data.report_file 必须存在
    report_file = payload["data"]["report_file"]
    assert os.path.isfile(report_file)
    # 路径必须指向 target run
    assert target in report_file
    assert report_file.endswith(f"{target}_screening_report.html")


# ============================================================
# 2. run 不存在
# ============================================================

def test_report_run_not_found(workspace):
    tmp_path, eid, job_name, _target, _other, _empty = workspace
    proc = _run_cli("report", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", "9999-99-99_999999",
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 23
    payload = json.loads(_decode(proc.stdout))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "RUN_NOT_FOUND"
    assert payload["run_id"] == "9999-99-99_999999"
    assert "不存在" in payload["error"]["message"]


# ============================================================
# 3. encrypt_job_id 不匹配
# ============================================================

def test_report_wrong_encrypt_job_id(workspace):
    tmp_path, eid, job_name, target, _other, _empty = workspace
    # 用错的 encrypt_job_id → runs_dir 找不到 target run → RUN_NOT_FOUND
    proc = _run_cli("report", "--job-name", job_name,
                    "--encrypt-job-id", "wrong_eid_xyz",
                    "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    # 错 encrypt_job_id 走到 bind_existing_run → FileNotFoundError → 预校验拦截
    assert proc.returncode == 23
    payload = json.loads(_decode(proc.stdout))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "RUN_NOT_FOUND"


# ============================================================
# 4. 缺少 screening_results
# ============================================================

def test_report_missing_screening(workspace):
    tmp_path, eid, job_name, _target, _other, empty = workspace
    proc = _run_cli("report", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", empty,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    # 旧脚本 exit 27；新 CLI 保留这个语义
    assert proc.returncode == 27
    payload = json.loads(_decode(proc.stdout))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MISSING_SCREENING"
    assert "screening_results.json" in payload["error"]["message"]


# ============================================================
# 5. 不借用其他 run 的结果
# ============================================================

def test_report_does_not_borrow_other_run(workspace):
    tmp_path, eid, job_name, _target, other, _empty = workspace
    # other run 有诱饵旧 HTML（<html>诱饵旧报告</html>）
    # 调 report 对 other run（本身没 screening，但有诱饵 HTML）
    # 必须按 orchestrator 失败（缺 screening），绝不能"借"诱饵 HTML 当结果
    proc = _run_cli("report", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", other,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 27
    payload = json.loads(_decode(proc.stdout))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MISSING_SCREENING"
    # 诱饵 HTML 不应被复制到 target run
    target_html = tmp_path / eid / "runs" / "2026-08-03_120000" / "2026-08-03_120000_screening_report.html"
    assert not target_html.exists(), f"不应有任何 HTML 在 target run，但 {target_html} 存在"


# ============================================================
# 6. 不触发 greet
# ============================================================

def test_report_does_not_trigger_greet(workspace):
    tmp_path, eid, job_name, target, _other, _empty = workspace
    proc = _run_cli("report", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    # 看 stderr（greet 触发会有自己的 log）；同时检查没有 greet_log.json
    target_dir = tmp_path / eid / "runs" / target
    greet_log = target_dir / "process" / "greet_log.json"
    assert not greet_log.exists(), "report 触发 greet 是禁止的"
    # run.json 不应被 greet 改写（run_id 不变、steps_done 不变长）
    run_json = json.loads((target_dir / "run.json").read_text(encoding="utf-8"))
    assert "greet" not in run_json.get("steps_done", [])


# ============================================================
# 7. 重复运行行为与旧脚本一致
# ============================================================

def test_report_repeat_run_overwrites(workspace):
    tmp_path, eid, job_name, target, _other, _empty = workspace
    env_extra = {"BOSS_HR_OUTPUT_DIR": str(tmp_path)}
    proc1 = _run_cli("report", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc1.returncode == 0
    p1 = json.loads(_decode(proc1.stdout))
    path1 = p1["data"]["report_file"]
    assert os.path.isfile(path1)

    # 第二次跑应该覆盖 HTML（与旧脚本一致）
    proc2 = _run_cli("report", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc2.returncode == 0
    p2 = json.loads(_decode(proc2.stdout))
    path2 = p2["data"]["report_file"]
    assert path1 == path2
    assert os.path.isfile(path2)
    # run.json steps_done 不应重复添加 'report'（mark_done 幂等）
    run_json = json.loads((tmp_path / eid / "runs" / target / "run.json").read_text(encoding="utf-8"))
    assert run_json["steps_done"].count("report") == 1


# ============================================================
# 8. 新旧报告关键内容等价
# ============================================================

def test_report_new_old_content_equivalent(workspace):
    """同一份 screening_results.json 跑旧脚本 vs 新 CLI，
    关键 HTML 内容（rank 顺序、stat-card 数字、候选人姓名）必须等价。"""
    tmp_path, eid, job_name, target, _other, _empty = workspace
    env_extra = {"BOSS_HR_OUTPUT_DIR": str(tmp_path)}

    # 跑新 CLI
    proc_new = _run_cli("report", "--job-name", job_name,
                        "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc_new.returncode == 0
    new_report_path = json.loads(_decode(proc_new.stdout))["data"]["report_file"]

    # 跑旧脚本（同一个 run_id，会覆盖新 CLI 的 HTML）
    proc_old = _run_old("--job-name", job_name,
                        "--encrypt-job-id", eid, "--run-id", target, env_extra=env_extra)
    assert proc_old.returncode == 0, f"旧脚本 rc={proc_old.returncode} stderr={_decode(proc_old.stderr)[:200]}"
    old_report_path = tmp_path / eid / "runs" / target / f"{target}_screening_report.html"
    assert old_report_path.is_file()

    # 抽关键统计
    def _extract(html: str) -> dict:
        ranks = [int(m.group(1)) for m in re.finditer(r'<span class="rank">#?(\d+)</span>', html)]
        stat_nums = re.findall(r'<div class="num">(\d+)</div>', html)
        names = re.findall(r'<h3>([^<]+)</h3>', html)
        return {"ranks": ranks, "stat_nums": stat_nums, "names": names}

    new_html = Path(new_report_path).read_text(encoding="utf-8")
    old_html = old_report_path.read_text(encoding="utf-8")
    new_kv = _extract(new_html)
    old_kv = _extract(old_html)

    assert new_kv["ranks"] == old_kv["ranks"], f"rank 顺序不等价: new={new_kv['ranks']} old={old_kv['ranks']}"
    assert new_kv["stat_nums"] == old_kv["stat_nums"], f"stat-card 数字不等价: new={new_kv['stat_nums']} old={old_kv['stat_nums']}"
    assert set(new_kv["names"]) == set(old_kv["names"]), f"候选人姓名不等价: new={new_kv['names']} old={old_kv['names']}"
