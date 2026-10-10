"""_baseline_confirm.py — 跑旧 shared/confirm_run.py，记录基线（2026-08-03）

不依赖桌面真实数据；用 BOSS_HR_OUTPUT_DIR 指向 tmp_path，建一个 run + run.json（confirmed=false）。

跑旧脚本多次，记录：
- happy path（confirmed=false → true）
- 重复 confirm（已 true 再 confirm）
- run 不存在
- encrypt_job_id 不匹配
- 缺 --run-id（argparse）
- 缺 encrypt_job_id（参数错误）

run.json diff + 修改了哪些文件。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent  # tools/ → 工具包根
SCRIPT = TOOLKIT_ROOT / "shared" / "confirm_run.py"
SHARED = TOOLKIT_ROOT / "shared"


def _run(cmd: list[str], env: dict, cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=cwd, timeout=timeout)


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
        eid = "test_eid_confirm_baseline"
        job_name = "confirm_baseline_job"
        rid = "2026-08-03_120000"

        rd = tmp_path / eid / "runs" / rid / "process"
        rd.mkdir(parents=True, exist_ok=True)
        # run.json：init_run_state 后的状态（confirmed=false）
        (tmp_path / eid / "runs" / rid / "run.json").write_text(json.dumps({
            "run_id": rid, "encrypt_job_id": eid,
            "started_at": "2026-08-03 12:00:00",
            "confirmed": False, "user_confirmed_at": None,
            "steps_done": [], "last_step": None, "last_step_at": None,
            "finished": False, "finished_at": None,
        }, ensure_ascii=False), encoding="utf-8")
        (rd / "job_detail.json").write_text(json.dumps({
            "jobName": job_name, "encryptJobId": eid,
        }, ensure_ascii=False), encoding="utf-8")

        # 写一个诱饵旧 run.json（验证不借用）
        other_rid = "2026-08-02_120000"
        (tmp_path / eid / "runs" / other_rid).mkdir(parents=True, exist_ok=True)
        (tmp_path / eid / "runs" / other_rid / "run.json").write_text(json.dumps({
            "run_id": other_rid, "encrypt_job_id": eid,
            "confirmed": True, "user_confirmed_at": "2026-08-02 13:00:00",
            "started_at": "2026-08-02 12:00:00",
            "steps_done": ["jd", "download", "score", "report"],
            "last_step": "report", "finished": True,
            "finished_at": "2026-08-02 18:00:00",
        }, ensure_ascii=False), encoding="utf-8")

        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": str(SHARED), "BOSS_HR_OUTPUT_DIR": str(tmp_path)}

        # 1) happy path
        cmd1 = [sys.executable, "-X", "utf8", str(SCRIPT),
                "--job-name", job_name, "--encrypt-job-id", eid, "--run-id", rid]
        before = (tmp_path / eid / "runs" / rid / "run.json").read_text(encoding="utf-8")
        proc1 = _run(cmd1, env=env, cwd=str(SHARED))
        after1 = (tmp_path / eid / "runs" / rid / "run.json").read_text(encoding="utf-8")

        # 2) repeat confirm
        proc2 = _run(cmd1, env=env, cwd=str(SHARED))

        # 3) --status（仅查询）
        cmd3 = [sys.executable, "-X", "utf8", str(SCRIPT),
                "--job-name", job_name, "--encrypt-job-id", eid, "--run-id", rid, "--status"]
        proc3 = _run(cmd3, env=env, cwd=str(SHARED))

        # 4) encrypt_job_id 不匹配
        cmd4 = [sys.executable, "-X", "utf8", str(SCRIPT),
                "--job-name", job_name, "--encrypt-job-id", "wrong_eid", "--run-id", rid]
        proc4 = _run(cmd4, env=env, cwd=str(SHARED))

        # 5) run_id 不存在
        cmd5 = [sys.executable, "-X", "utf8", str(SCRIPT),
                "--job-name", job_name, "--encrypt-job-id", eid, "--run-id", "9999-99-99_999999"]
        proc5 = _run(cmd5, env=env, cwd=str(SHARED))

        # 6) 缺 --run-id
        cmd6 = [sys.executable, "-X", "utf8", str(SCRIPT),
                "--job-name", job_name, "--encrypt-job-id", eid]
        proc6 = _run(cmd6, env=env, cwd=str(SHARED))

        # 7) 缺 encrypt_job_id（无 env）
        env_no_eid = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                      "PYTHONPATH": str(SHARED)}
        cmd7 = [sys.executable, "-X", "utf8", str(SCRIPT),
                "--job-name", job_name, "--run-id", rid]
        proc7 = _run(cmd7, env=env_no_eid, cwd=str(SHARED))

        # 验证 other run.json 没被动
        other_after = (tmp_path / eid / "runs" / other_rid / "run.json").read_text(encoding="utf-8")

        baseline = {
            "happy": {
                "rc": proc1.returncode, "stdout": proc1.stdout, "stderr": proc1.stderr,
                "run_json_before": json.loads(before),
                "run_json_after": json.loads(after1),
            },
            "repeat": {
                "rc": proc2.returncode, "stdout": proc2.stdout, "stderr": proc2.stderr,
            },
            "status_only": {
                "rc": proc3.returncode, "stdout": proc3.stdout, "stderr": proc3.stderr,
            },
            "wrong_encrypt_job_id": {
                "rc": proc4.returncode, "stdout": proc4.stdout, "stderr": proc4.stderr,
            },
            "no_such_run": {
                "rc": proc5.returncode, "stdout": proc5.stdout, "stderr": proc5.stderr,
            },
            "missing_run_id_argv": {
                "rc": proc6.returncode, "stdout": proc6.stdout, "stderr": proc6.stderr,
            },
            "missing_encrypt_job_id": {
                "rc": proc7.returncode, "stdout": proc7.stdout, "stderr": proc7.stderr,
            },
            "other_run_unchanged": other_after == (tmp_path / eid / "runs" / other_rid / "run.json").read_text(encoding="utf-8"),
            "other_run_after": json.loads(other_after),
        }
        out = TOOLKIT_ROOT / "artifacts" / "refactor" / "confirm-baseline.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
