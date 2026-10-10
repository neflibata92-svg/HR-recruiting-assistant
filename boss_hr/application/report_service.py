"""boss_hr.application.report_service — report 命令业务逻辑。

职责：
  - 校验 run 存在（预校验，避免子进程抛 FileNotFoundError）
  - 通过 adapters/legacy_runner 调 generate_html_report.py
  - 把子进程返回包装成 CommandResult
"""
from __future__ import annotations
import os
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


def generate_report(*, job_name: str, encrypt_job_id: str | None,
                    run_id: str | None) -> CommandResult:
    """report 命令业务实现。

    流程：
      1) 校验 encrypt_job_id / run_id
      2) bind_existing_run 预校验（捕获 FileNotFoundError → 提前 exit 23）
      3) 调 legacy_runner.run_legacy_cli("generate_html_report", ...)
      4) 解析子进程 stdout / 退出码 → CommandResult
    """
    from shared.run_orchestrator import (
        RunOrchestrator,
        EXIT_CODE_RUN_NOT_FOUND,
        EXIT_CODE_RUN_JOB_MISMATCH,
    )

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

    # 调旧脚本
    result = run_legacy_cli(
        "generate_html_report",
        [
            "--job-name", job_name,
            "--encrypt-job-id", eid,
            "--run-id", bound_run_id,
        ],
        timeout=60,
        extract_report_path=True,
        eid=eid, run_id=bound_run_id, job_name=job_name,
    )

    if result.returncode != 0:
        # 把子脚本 blocked JSON 的 message 拿出来（更详细）
        better_msg = try_extract_blocked_message(result.stdout)
        unified = legacy_error(result)
        if better_msg:
            unified = UnifiedError(
                code=unified.code, message=better_msg,
                subprocess_returncode=unified.subprocess_returncode,
            )
        # stderr 写日志（由 cli.py 处理）
        return error(
            error_obj=unified,
            run_id=bound_run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode(result.returncode),  # 保留子进程退出码
        )

    # 成功：report_file 必须真存在
    if not result.report_file or not os.path.isfile(result.report_file):
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.INTERNAL,
                message=f"子脚本 rc=0 但报告文件未生成：{result.report_file}",
            ),
            run_id=bound_run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode.INTERNAL,
        )

    return ok(
        status="report_ready",
        run_id=bound_run_id,
        encrypt_job_id=eid, job_name=job_name,
        data={"report_file": os.path.abspath(result.report_file)},
        next_action="greet_optional",
    )


__all__ = ["generate_report"]
