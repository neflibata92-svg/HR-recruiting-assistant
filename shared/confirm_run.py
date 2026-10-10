#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
confirm_run.py — 用户『继续』确认的 CLI 入口（2026-07-30）。

设计动机：
  Step 1 (boss_jd.py) 完成后 → init_run_state() 写 run.json（confirmed=false）。
  智能体必须等用户在 BOSS 调整完筛选条件后调本脚本，把 confirmed=true。

约束：
  - --run-id 必填（run_id 是数据边界）
  - 调 RunOrchestrator.confirm_run(run_id)
  - 输出 JSON 格式（stdout），智能体易解析

用法：
  python -X utf8 shared/confirm_run.py \
    --job-name "结构设计、研发工程师" \
    --encrypt-job-id "DemoJobId000000000000000000001" \
    --run-id "2026-07-30_103000"

  # 仅查询不修改：
  python -X utf8 shared/confirm_run.py \
    --job-name "..." --encrypt-job-id "..." --run-id "..." --status

退出码：
  0  — 确认成功 / 查看成功
  1  — 参数错误
  22 — 缺少 --run-id
  23 — run_id 对应目录不存在
  24 — run_id 与岗位不匹配
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_encoding  # noqa: E402  # 强制 Windows UTF-8 stdout
from output_manager import resolve_encrypt_job_id
from run_orchestrator import (
    RunOrchestrator,
    EXIT_CODE_MISSING_RUN_ID,
    EXIT_CODE_RUN_NOT_FOUND,
    EXIT_CODE_RUN_JOB_MISMATCH,
)


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def confirm_run(job_name: str, encrypt_job_id: str, run_id: str | None,
                status_only: bool = False) -> int:
    if not run_id:
        _emit({
            "status": "missing_run_id",
            "exit_code": EXIT_CODE_MISSING_RUN_ID,
            "run_id": None,
            "message": ("缺少 --run-id。run_id 是数据边界，禁止自动选择历史 run。\n"
                        "请从 Step 1 (boss_jd.py) 的输出中获取 run_id。"),
        })
        return EXIT_CODE_MISSING_RUN_ID

    orch = RunOrchestrator(job_name, encrypt_job_id=encrypt_job_id)
    try:
        run_id = orch.bind_existing_run(run_id)
    except SystemExit:
        raise
    except FileNotFoundError as e:
        _emit({"status": "blocked", "exit_code": EXIT_CODE_RUN_NOT_FOUND,
               "run_id": run_id, "message": str(e)})
        return EXIT_CODE_RUN_NOT_FOUND
    except RuntimeError as e:
        _emit({"status": "blocked", "exit_code": EXIT_CODE_RUN_JOB_MISMATCH,
               "run_id": run_id, "message": str(e)})
        return EXIT_CODE_RUN_JOB_MISMATCH

    if status_only:
        _emit({
            "status": "ok",
            "run_id": run_id,
            "confirmed": orch.is_confirmed(run_id),
            "message": "已查询，未修改状态。",
        })
        return 0

    # 切 confirmed=true
    orch.confirm_run(run_id)
    _emit({
        "status": "confirmed",
        "run_id": run_id,
        "confirmed": True,
        "message": ("确认成功。run.json.confirmed=true。\n"
                    "下游脚本（recommend_list.py / recommend_download.py）现在可以执行 Step 2~5。"),
    })
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="用户『继续』确认 CLI：把 run.json.confirmed 切到 true。",
    )
    parser.add_argument("--job-name", required=True, help="岗位名（jobs.json metadata）")
    parser.add_argument("--encrypt-job-id", default=None,
                        help="BOSS encryptJobId（推荐；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）")
    parser.add_argument("--run-id", required=True,
                        help="【必填】run_id 是数据边界。")
    parser.add_argument("--status", action="store_true",
                        help="仅查看 confirmed 状态，不修改。")
    args = parser.parse_args()

    encrypt_job_id = resolve_encrypt_job_id(args.encrypt_job_id)
    if not encrypt_job_id:
        _emit({
            "status": "error",
            "message": ("缺少 encrypt_job_id。\n"
                        "  传 --encrypt-job-id，或设置 env BOSS_HR_ENCRYPT_JOB_ID。"),
        })
        sys.exit(1)

    try:
        code = confirm_run(args.job_name, encrypt_job_id, args.run_id, args.status)
    except Exception as e:
        _emit({"status": "error", "message": str(e)})
        sys.exit(1)
    sys.exit(code)