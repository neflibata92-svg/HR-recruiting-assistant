# -*- coding: utf-8 -*-
"""boss_hr.commands.status — status 命令处理。

status 命令保留第一轮 schema（status:"ok"/"blocked"/"error" + 顶层字段）。
"""
from __future__ import annotations
import argparse
from typing import Tuple

from boss_hr.application.status_service import get_status
from boss_hr.commands._argparse_helpers import (
    add_required_arguments, require_encrypt_job_id,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_required_arguments(parser)


def run(args: argparse.Namespace) -> Tuple[int, dict]:
    eid = require_encrypt_job_id(args._parser, args)
    return get_status(
        job_name=args.job_name,
        encrypt_job_id=eid,
        run_id=args.run_id,
    )


__all__ = ["add_arguments", "run"]
