"""_smoke_report.py — 手动烟测新 boss_hr report（2026-08-03）

对比 _baseline_report.py 的输入 fixture，跑新 CLI，对比：
- returncode
- JSON schema
- 报告路径
- 报告关键统计（stat-card 数字、rank 顺序）
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE
CLI = TOOLKIT_ROOT / "boss_hr" / "cli.py"
SHARED = TOOLKIT_ROOT / "shared"


def _run(args: list[str], env: dict, cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, env=env, cwd=cwd, timeout=timeout)


def _decode(b: bytes | None) -> str:
    if not b:
        return ""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        eid = "test_eid_smoke"
        job_name = "smoke_job"
        target_run = "2026-08-03_120000"
        empty_run = "2026-08-03_130000"

        for rid in (target_run, empty_run):
            rd = tmp_path / eid / "runs" / rid / "process"
            rd.mkdir(parents=True, exist_ok=True)
            (tmp_path / eid / "runs" / rid / "run.json").write_text(json.dumps({
                "run_id": rid, "encrypt_job_id": eid,
                "started_at": "2026-08-03 12:00:00", "confirmed": True,
                "steps_done": ["jd", "download", "score"], "last_step": "score",
                "finished": False, "finished_at": None,
            }, ensure_ascii=False), encoding="utf-8")
            (rd / "job_detail.json").write_text(json.dumps({
                "jobName": job_name, "encryptJobId": eid,
            }, ensure_ascii=False), encoding="utf-8")

        screening = {
            "job_name": job_name, "run_id": target_run,
            "summary": {"total": 2, "recommend": 1, "pending": 0, "reject": 1},
            "dimension_labels": ["学历", "工作经验", "技能", "项目", "专业"],
            "candidates": [
                {"rank": 1, "name": "张三", "tier": "推荐", "total": 78.5,
                 "school": "辽宁工业大学", "work_years": "5 年", "current_role": "结构设计",
                 "hard_pass": True, "dimensions": [
                     {"pct": 70, "weighted": 17.5, "weight": 25, "reason": ""},
                     {"pct": 80, "weighted": 20.0, "weight": 25, "reason": ""},
                     {"pct": 85, "weighted": 21.25, "weight": 25, "reason": ""},
                     {"pct": 75, "weighted": 11.25, "weight": 15, "reason": ""},
                     {"pct": 85, "weighted": 8.5, "weight": 10, "reason": ""},
                 ], "highlights": ["亮点"], "concerns": []},
                {"rank": 2, "name": "王五", "tier": "不推荐", "total": 45.0,
                 "school": "野鸡大学", "work_years": "1 年", "current_role": "实习",
                 "hard_pass": True, "dimensions": [
                     {"pct": 50, "weighted": 12.5, "weight": 25, "reason": ""},
                     {"pct": 40, "weighted": 10.0, "weight": 25, "reason": ""},
                     {"pct": 50, "weighted": 12.5, "weight": 25, "reason": ""},
                     {"pct": 40, "weighted": 6.0, "weight": 15, "reason": ""},
                     {"pct": 40, "weighted": 4.0, "weight": 10, "reason": ""},
                 ], "highlights": [], "concerns": ["经验浅"]},
            ],
            "actions": {
                "recommend": [{"name": "张三", "score": 78.5,
                               "background": "亮点", "action": "约面试"}],
                "pending": [],
                "reject": [{"name": "王五", "score": 45.0, "concerns": "经验浅"}],
            },
            "meta": {"title": "smoke", "subtitle": "", "job": {}, "type_judgment": {}, "core_requirements": []},
        }
        (tmp_path / eid / "runs" / target_run / "process" / "screening_results.json").write_text(
            json.dumps(screening, ensure_ascii=False), encoding="utf-8")

        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": str(SHARED), "BOSS_HR_OUTPUT_DIR": str(tmp_path)}

        # ---- 1. happy path ----
        cmd = [sys.executable, "-X", "utf8", str(CLI), "report",
               "--job-name", job_name, "--encrypt-job-id", eid, "--run-id", target_run]
        proc = _run(cmd, env=env, cwd=str(TOOLKIT_ROOT))

        # ---- 2. missing screening ----
        cmd2 = [sys.executable, "-X", "utf8", str(CLI), "report",
                "--job-name", job_name, "--encrypt-job-id", eid, "--run-id", empty_run]
        proc_missing = _run(cmd2, env=env, cwd=str(TOOLKIT_ROOT))

        # ---- 3. no such run ----
        cmd3 = [sys.executable, "-X", "utf8", str(CLI), "report",
                "--job-name", job_name, "--encrypt-job-id", eid, "--run-id", "9999-99-99_999999"]
        proc_no_run = _run(cmd3, env=env, cwd=str(TOOLKIT_ROOT))

        # ---- 4. wrong encrypt_job_id ----
        cmd4 = [sys.executable, "-X", "utf8", str(CLI), "report",
                "--job-name", job_name, "--encrypt-job-id", "wrong_eid", "--run-id", target_run]
        proc_wrong = _run(cmd4, env=env, cwd=str(TOOLKIT_ROOT))

        # ---- 5. missing run_id ----
        cmd5 = [sys.executable, "-X", "utf8", str(CLI), "report",
                "--job-name", job_name, "--encrypt-job-id", eid]
        proc_no_argv = _run(cmd5, env=env, cwd=str(TOOLKIT_ROOT))

        # ---- 6. missing encrypt_job_id（无 env） ----
        env_no_eid = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                      "PYTHONPATH": str(SHARED)}  # no BOSS_HR_OUTPUT_DIR no encrypt_job_id
        cmd6 = [sys.executable, "-X", "utf8", str(CLI), "report",
                "--job-name", job_name, "--run-id", target_run]
        proc_no_eid = _run(cmd6, env=env_no_eid, cwd=str(TOOLKIT_ROOT))

        out = {
            "happy_path": {
                "rc": proc.returncode,
                "stdout": _decode(proc.stdout),
                "stderr": _decode(proc.stderr),
            },
            "missing_screening": {
                "rc": proc_missing.returncode,
                "stdout": _decode(proc_missing.stdout),
                "stderr": _decode(proc_missing.stderr),
            },
            "no_such_run": {
                "rc": proc_no_run.returncode,
                "stdout": _decode(proc_no_run.stdout),
                "stderr": _decode(proc_no_run.stderr),
            },
            "wrong_encrypt_job_id": {
                "rc": proc_wrong.returncode,
                "stdout": _decode(proc_wrong.stdout),
                "stderr": _decode(proc_wrong.stderr),
            },
            "missing_run_id_argv": {
                "rc": proc_no_argv.returncode,
                "stdout": _decode(proc_no_argv.stdout),
                "stderr": _decode(proc_no_argv.stderr),
            },
            "missing_encrypt_job_id": {
                "rc": proc_no_eid.returncode,
                "stdout": _decode(proc_no_eid.stdout),
                "stderr": _decode(proc_no_eid.stderr),
            },
        }
        out_file = TOOLKIT_ROOT / "artifacts" / "refactor" / "report-smoke.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
