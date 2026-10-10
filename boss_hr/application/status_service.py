"""boss_hr.application.status_service — status 命令业务逻辑。

只读：扫描 runs/<run_id>/run.json + process/ 目录，推断 workflow_state。
不调子脚本、不写文件。

schema（第一轮固定，不改变）：
  成功：
    {status:"ok", command:"status", run_id, encrypt_job_id, job_name,
     workflow_state, confirmed, finished, last_step, last_step_at,
     steps_done, started_at, user_confirmed_at, finished_at,
     paths:{run_dir, process_dir, report_html},
     process_files:{...}}
  失败：
    {status:"error"|"blocked", command:"status", run_id, message, ...}
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BOSS_HR = _HERE.parent
_TOOLKIT_ROOT = _BOSS_HR.parent
sys.path.insert(0, str(_TOOLKIT_ROOT))
sys.path.insert(0, str(_TOOLKIT_ROOT / "shared"))


def _resolve_encrypt_job_id(cli_value: str | None) -> str | None:
    if cli_value:
        return cli_value
    return os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")


def _workflow_state(state: dict) -> str:
    steps_done = state.get("steps_done", [])
    finished = bool(state.get("finished"))
    if finished:
        return "finished"
    if not state.get("confirmed"):
        return "waiting_user_confirmation"
    if "jd" not in steps_done:
        return "ready_to_fetch"
    if "download" not in steps_done:
        return "ready_to_fetch"
    if "score" not in steps_done:
        return "ready_to_score"
    if "report" not in steps_done:
        return "ready_to_report"
    return "report_ready"


def get_status(*, job_name: str, encrypt_job_id: str | None,
               run_id: str | None) -> tuple[int, dict]:
    """status 命令业务实现。

    Returns:
        (exit_code, payload_dict)
        exit_code: 0 / 1 / 22 / 23 / 24
        payload_dict: 直接 emit 的 JSON（已含 command:"status"）

    返回 tuple 是为了让 status 命令保持第一轮 schema（与 ok/error 通用
    schema 不一致；后续如需统一再升级）。
    """
    from shared.output_manager import JobOutputManager
    from shared.run_orchestrator import (
        RunOrchestrator,
        EXIT_CODE_RUN_NOT_FOUND,
        EXIT_CODE_RUN_JOB_MISMATCH,
    )

    eid = _resolve_encrypt_job_id(encrypt_job_id)
    if not eid:
        return 1, {  # 与第一轮 status schema 一致：缺 eid rc=1
            "status": "error",
            "command": "status",
            "message": "缺少 encrypt_job_id（传 --encrypt-job-id 或设环境变量 BOSS_HR_ENCRYPT_JOB_ID）",
        }

    if not run_id:
        return 22, {
            "status": "error",
            "command": "status",
            "run_id": None,
            "message": "缺少 --run-id（run_id 是数据边界，禁止自动选择历史 run）",
        }

    orch = RunOrchestrator(job_name, encrypt_job_id=eid)
    try:
        bound_run_id = orch.bind_existing_run(run_id)
    except FileNotFoundError:
        return EXIT_CODE_RUN_NOT_FOUND, {
            "status": "blocked",
            "command": "status",
            "run_id": run_id,
            "encrypt_job_id": eid,
            "message": f"run_id={run_id} 在岗位目录下不存在",
        }
    except RuntimeError as e:
        return EXIT_CODE_RUN_JOB_MISMATCH, {
            "status": "blocked",
            "command": "status",
            "run_id": run_id,
            "encrypt_job_id": eid,
            "message": str(e),
        }

    out = JobOutputManager(job_name, encrypt_job_id=eid, run_id=bound_run_id, lazy=True)
    run_json_path = os.path.join(out.runs_dir, bound_run_id, "run.json")
    state: dict = {}
    if os.path.exists(run_json_path):
        try:
            with open(run_json_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            state = {"_read_error": str(e)}

    process_dir = os.path.join(out.runs_dir, bound_run_id, "process")
    files = {}
    if os.path.isdir(process_dir):
        for fn in sorted(os.listdir(process_dir)):
            full = os.path.join(process_dir, fn)
            if os.path.isdir(full):
                files[fn] = {"type": "dir", "entries": sorted(os.listdir(full))[:20]}
            else:
                try:
                    files[fn] = {"type": "file", "size": os.path.getsize(full)}
                except OSError:
                    files[fn] = {"type": "file"}

    return 0, {
        "status": "ok",
        "command": "status",
        "run_id": bound_run_id,
        "encrypt_job_id": eid,
        "job_name": job_name,
        "workflow_state": _workflow_state(state),
        "confirmed": bool(state.get("confirmed")),
        "finished": bool(state.get("finished")),
        "last_step": state.get("last_step"),
        "last_step_at": state.get("last_step_at"),
        "steps_done": state.get("steps_done", []),
        "started_at": state.get("started_at"),
        "user_confirmed_at": state.get("user_confirmed_at"),
        "finished_at": state.get("finished_at"),
        "paths": {
            "run_dir": os.path.join(out.runs_dir, bound_run_id),
            "process_dir": process_dir,
            "report_html": os.path.join(out.runs_dir, bound_run_id,
                                        f"{bound_run_id}_screening_report.html"),
        },
        "process_files": files,
    }


__all__ = ["get_status"]
