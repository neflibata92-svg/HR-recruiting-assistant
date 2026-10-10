# -*- coding: utf-8 -*-
"""boss_hr.commands._argparse_helpers — argparse 必填参数辅助。

统一 CLI 行为：
  缺 --job-name       → argparse rc=2
  缺 --encrypt-job-id → argparse rc=2
  缺 --run-id         → argparse rc=2

`--encrypt-job-id` 保留 env `BOSS_HR_ENCRYPT_JOB_ID` 兜底（兼容旧用法），
但**从 CLI 行为上仍是必填**：env 缺失 + CLI 缺失 → argparse.error → rc=2。
"""
from __future__ import annotations
import argparse
import os


def add_required_arguments(parser: argparse.ArgumentParser) -> None:
    """注册 status / report / confirm / score 等命令的必填参数。

    不直接 parser.add_argument(required=True)，因为 --encrypt-job-id 要兼容 env。
    本函数只注册参数；强制校验在 require_or_env() 里做（args parse 完之后）。
    """
    parser.add_argument("--job-name", required=True, help="岗位名")
    parser.add_argument("--encrypt-job-id", default=None,
                        help="BOSS encryptJobId（推荐；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）")
    parser.add_argument("--run-id", required=True, help="【必填】run_id 是数据边界")


def resolve_encrypt_job_id(cli_value: str | None) -> str | None:
    """CLI 透传 > 环境变量 > None。"""
    if cli_value:
        return cli_value
    return os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")


def require_encrypt_job_id(parser: argparse.ArgumentParser, ns: argparse.Namespace) -> str:
    """缺 --encrypt-job-id（且 env BOSS_HR_ENCRYPT_JOB_ID 也没有）→ argparse.error(rc=2)。

    返回：解析后的 encrypt_job_id 字符串（非空）。
    """
    eid = resolve_encrypt_job_id(getattr(ns, "encrypt_job_id", None))
    if not eid:
        parser.error(
            "缺少 --encrypt-job-id（亦可通过环境变量 BOSS_HR_ENCRYPT_JOB_ID 传入）"
        )
    return eid


__all__ = [
    "add_required_arguments",
    "resolve_encrypt_job_id",
    "require_encrypt_job_id",
]
