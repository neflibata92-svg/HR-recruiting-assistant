# -*- coding: utf-8 -*-
"""boss_hr.commands.greet — greet 命令处理。"""
from __future__ import annotations
import argparse

from boss_hr.contracts.results import CommandResult
from boss_hr.application.greet_service import greet_candidates
from boss_hr.commands._argparse_helpers import (
    add_required_arguments, require_encrypt_job_id,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_required_arguments(parser)
    parser.add_argument(
        "--only-names", default=None,
        help="逗号分隔，精准点名要打招呼的候选人（给定时忽略 --threshold / --max）",
    )
    parser.add_argument(
        "--threshold", type=float, default=70.0,
        help="score 阈值，≥ 阈值的候选人会被招呼（默认 70）",
    )
    parser.add_argument(
        "--max", type=int, default=10, dest="max_count",
        help="最多打招呼人数（默认 10）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑：只定位不点击",
    )


def run(args: argparse.Namespace) -> CommandResult:
    eid = require_encrypt_job_id(args._parser, args)
    return greet_candidates(
        job_name=args.job_name,
        encrypt_job_id=eid,
        run_id=args.run_id,
        only_names=args.only_names,
        threshold=args.threshold,
        max_count=args.max_count,
        dry_run=args.dry_run,
    )


__all__ = ["add_arguments", "run"]
