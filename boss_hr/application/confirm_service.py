# -*- coding: utf-8 -*-
"""boss_hr.application.confirm_service — confirm 命令业务逻辑。

职责：
  - 校验 encrypt_job_id / run_id
  - 预校验 run 存在（拦截 FileNotFoundError → 23）
  - 调 shared/cli_runner.run_python_cli("confirm_run", ...) 复用现有
    confirm_run.py 业务脚本（不直接编辑 run.json，不写新实现）
  - 解析子进程 stdout 的 JSON payload 包装成 CommandResult

确认成功 schema：
  {ok:true, command:"confirm", status:"confirmed", run_id,
   encrypt_job_id, job_name, data:{confirmed, user_confirmed_at},
   next_action:"fetch"}

确认失败：
  {ok:false, command:"confirm", run_id, encrypt_job_id,
   error:{code, message}}
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BOSS_HR = _HERE.parent
_TOOLKIT_ROOT = _BOSS_HR.parent
sys.path.insert(0, str(_TOOLKIT_ROOT))
sys.path.insert(0, str(_TOOLKIT_ROOT / "shared"))

from boss_hr.contracts.results import CommandResult, ok, error
from boss_hr.contracts.errors import (
    ExitCode, ErrorCode, UnifiedError,
)
from boss_hr.adapters.legacy_runner import (
    run_legacy_cli, legacy_error, try_extract_blocked_message,
)


def _resolve_encrypt_job_id(cli_value: str | None) -> str | None:
    if cli_value:
        return cli_value
    return os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")


def _read_confirmed(run_dir: str, run_id: str) -> tuple[bool, str | None]:
    """从 run.json 读 confirmed / user_confirmed_at（不修改）。"""
    path = os.path.join(run_dir, run_id, "run.json")
    if not os.path.exists(path):
        return False, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False, None
    return bool(data.get("confirmed")), data.get("user_confirmed_at")


def confirm_run(*, job_name: str, encrypt_job_id: str | None,
                run_id: str | None) -> CommandResult:
    """confirm 命令业务实现。

    流程：
      1) 校验 encrypt_job_id / run_id
      2) bind_existing_run 预校验（捕获 FileNotFoundError → 23 / RuntimeError → 24）
      3) 调 cli_runner.run_python_cli("confirm_run", [args])
      4) 解析子进程 stdout 的 JSON payload + exit code → CommandResult
    """
    from shared.run_orchestrator import (
        RunOrchestrator,
        EXIT_CODE_RUN_NOT_FOUND,
        EXIT_CODE_RUN_JOB_MISMATCH,
    )
    from shared.output_manager import JobOutputManager

    eid = _resolve_encrypt_job_id(encrypt_job_id)
    if not eid:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.MISSING_ENCRYPT_JOB_ID,
                message="缺少 encrypt_job_id（传 --encrypt-job-id 或设环境变量 BOSS_HR_ENCRYPT_JOB_ID）",
            ),
            run_id=run_id, exit_code=ExitCode.GENERIC,  # 1
        )

    if not run_id:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.MISSING_RUN_ID,
                message="缺少 --run-id（run_id 是数据边界，禁止自动选择历史 run）",
            ),
            exit_code=ExitCode.MISSING_RUN_ID,  # 2
        )

    # 预校验 run 存在 + encrypt_job_id 匹配
    orch = RunOrchestrator(job_name, encrypt_job_id=eid)
    try:
        bound_run_id = orch.bind_existing_run(run_id)
    except FileNotFoundError:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.RUN_NOT_FOUND,
                message=f"run_id={run_id} 在岗位目录下不存在",
            ),
            run_id=run_id, encrypt_job_id=eid,
            exit_code=ExitCode(EXIT_CODE_RUN_NOT_FOUND),  # 23
        )
    except RuntimeError as e:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.JOB_MISMATCH,
                message=str(e),
            ),
            run_id=run_id, encrypt_job_id=eid,
            exit_code=ExitCode(EXIT_CODE_RUN_JOB_MISMATCH),  # 24
        )

    # 调旧 confirm_run.py（通过 cli_runner 复用，stdout 隔离）
    result = run_legacy_cli(
        "confirm_run",
        [
            "--job-name", job_name,
            "--encrypt-job-id", eid,
            "--run-id", bound_run_id,
        ],
        timeout=30,
    )

    if result.returncode != 0:
        # 优先用子进程 blocked JSON 的 message；否则用默认
        better_msg = try_extract_blocked_message(result.stdout)
        unified = legacy_error(result)
        if better_msg:
            unified = UnifiedError(
                code=unified.code, message=better_msg,
                subprocess_returncode=unified.subprocess_returncode,
            )
        return error(
            error_obj=unified,
            run_id=bound_run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode(result.returncode),
        )

    # 成功：从 run.json 读 confirmed / user_confirmed_at
    out = JobOutputManager(job_name, encrypt_job_id=eid, run_id=bound_run_id, lazy=True)
    confirmed, user_confirmed_at = _read_confirmed(out.runs_dir, bound_run_id)

    return ok(
        status="confirmed",
        run_id=bound_run_id,
        encrypt_job_id=eid, job_name=job_name,
        data={
            "confirmed": confirmed,
            "user_confirmed_at": user_confirmed_at,
        },
        next_action="fetch",
    )


__all__ = ["confirm_run"]
