# -*- coding: utf-8 -*-
"""boss_hr.commands.start — start 命令处理（v1.1.3）。

start 的公开语义固定为"创建一次全新的筛选任务"：
- query 必填（岗位名称 / jobId / encryptJobId）
- --job-name 可选（实时解析后用 BOSS 真名）
- --encrypt-job-id 可选（与实时解析结果一致性校验）
- --no-auto-launch 调试/测试用：不自动启动 Edge
- --login-wait-seconds 人工调试兼容选项：>=1 才在 CLI 内阻塞轮询扫码；
  默认 0 → 不阻塞，立即返回 waiting_user_login
- **不接受 --run-id**（start 必须创建新 run，不复用旧任务）
- 不自动调 confirm / fetch / score
"""
from __future__ import annotations
import argparse
import os

from boss_hr.contracts.results import CommandResult
from boss_hr.application.start_service import start_new_run


def _positive_int_or_zero(value: str) -> int:
    """argparse type：只接受 >= 0 的整数；负数 → 直接 argparse.error。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"--login-wait-seconds 必须是整数（当前 {value!r}）"
        )
    if n < 0:
        raise argparse.ArgumentTypeError(
            f"--login-wait-seconds 必须 >= 0（当前 {n}）；"
            "0 = 不阻塞扫码，立即返回 waiting_user_login；"
            ">0 = CLI 内阻塞轮询，最多等 N 秒（人工调试兼容选项）"
        )
    return n


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """start 公开参数（v1.1.3）。

    - query：必填位置参数。BOSS 实时岗位目录会自动解析：
        完整 encryptJobId | 数字 jobId | 岗位中文名（精确优先 / 模糊兜底）
    - --job-name：可选；最终值优先用实时解析出的 jobName
    - --encrypt-job-id：可选；与实时解析结果不一致会立即报错
    - --no-auto-launch：调试/测试用；不自动启动 Edge
    - --login-wait-seconds：>=0；默认 0。
        0 → start 不阻塞扫码等待，打开登录页后立即返回 waiting_user_login，
            由 Agent / 用户重复 start 复核登录态（v1.1.3 默认，**Agent 应不传**）
        >0 → CLI 内阻塞轮询登录，最多等 N 秒（**仅人工调试兼容**，不推荐 Agent）
        负数 → argparse 拒绝
    """
    parser.add_argument(
        "query",
        help="岗位名称 / jobId 数字 / 完整 encryptJobId（实时由 BOSS 解析）",
    )
    parser.add_argument(
        "--job-name", default=None,
        help="岗位中文名（可选；实时解析会用 BOSS 真名覆盖）",
    )
    parser.add_argument(
        "--encrypt-job-id", default=None,
        help="可选一致性校验：与实时解析结果不一致会立即停止",
    )
    parser.add_argument(
        "--no-auto-launch", action="store_true",
        help="不自动启动 Edge（调试/测试用；缺 CDP 直接返回 CDP_NOT_RUNNING）",
    )
    parser.add_argument(
        "--login-wait-seconds", type=_positive_int_or_zero, default=0,
        help=(
            "等待用户扫码的秒数（默认 0）。0=不阻塞、立即返回 waiting_user_login "
            "（v1.1.3 默认，Agent 应不传）；>0=CLI 内阻塞轮询最多 N 秒（仅人工调试）。"
            "负数被拒绝。"
        ),
    )


def run(args: argparse.Namespace) -> CommandResult:
    eid = args.encrypt_job_id or os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")
    login_wait = int(getattr(args, "login_wait_seconds", 0) or 0)
    return start_new_run(
        query=args.query,
        job_name=args.job_name,
        encrypt_job_id=eid,
        auto_launch_browser=not bool(getattr(args, "no_auto_launch", False)),
        login_wait_seconds=login_wait,
    )


__all__ = ["add_arguments", "run"]